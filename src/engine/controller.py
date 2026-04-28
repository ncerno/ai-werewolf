"""游戏控制器：回合调度、阶段推进、事件回调。"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Awaitable, Callable, Optional

from .state import GameState, Phase, Player, Role, Faction
from .rules import (
    check_winner,
    get_night_order,
    resolve_wolf_votes,
    resolve_election,
    tally_votes,
    validate_action,
)

EventCallback = Callable[[str, dict], Awaitable[None]]


def create_players() -> list[Player]:
    """创建标准 12 人局玩家列表。"""
    roles = [
        Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF,
        Role.SEER, Role.WITCH, Role.HUNTER, Role.FOOL,
        Role.VILLAGER, Role.VILLAGER, Role.VILLAGER, Role.VILLAGER,
    ]
    random.shuffle(roles)

    players = []
    for i, role in enumerate(roles, 1):
        p = Player(player_id=i, role=role)
        if role == Role.WITCH:
            p.witch_save_available = True
            p.witch_poison_available = True
            p.witch_knows_dead = True
        if role == Role.HUNTER:
            p.hunter_can_shoot = True
        players.append(p)
    return players


class GameController:
    """游戏调度器。

    支持三种模式的回调接口：
    - on_event: 游戏事件推送（日志、状态变更）
    - on_need_llm_decision: 需要 LLM 决策时调用（返回决策文本）
    - on_need_human_input: 需要人类输入时调用（上帝模式/玩家模式）
    """

    def __init__(self):
        self.state: Optional[GameState] = None
        self._event_callback: Optional[EventCallback] = None
        self._mode: str = "auto"
        self._agents: dict[int, object] = {}   # {player_id: PlayerAgent}
        self._config: dict = {}
        self._human_input_event = asyncio.Event()
        self._human_decision: dict | None = None
        self._human_player_id: int | None = None

    # ============================================================
    # 游戏生命周期
    # ============================================================

    def init_game(self, mode: str = "auto", config: dict | None = None,
                  human_player_id: int | None = None):
        """初始化新游戏。"""
        from ..agent.player import PlayerAgent
        from ..utils.config import get_llm_config_for_role

        players = create_players()
        self.state = GameState(players=players)
        self._mode = mode
        self._config = config or {}
        self._human_player_id = human_player_id
        self._human_decision = None
        self._human_input_event.clear()

        # 为每个玩家创建 PlayerAgent（human player 也需要 agent 用于 spectator）
        for player in players:
            role_str = player.role.value
            model_config = get_llm_config_for_role(role_str, self._config)
            agent = PlayerAgent(player.player_id, role_str, model_config, self.state)
            self._agents[player.player_id] = agent

        # 狼人互相告知队友
        wolf_ids = [p.player_id for p in players if p.role == Role.WEREWOLF]
        for wid in wolf_ids:
            teammates = [t for t in wolf_ids if t != wid]
            self._agents[wid].observe(
                f"[系统] 你的狼队友是：{'、'.join(f'{t}号' for t in teammates)}"
            )

        init_data = {"mode": mode, "players": len(players)}
        if human_player_id:
            human_p = self.state.get_player(human_player_id)
            init_data["human_player_id"] = human_player_id
            init_data["human_role"] = human_p.role.value if human_p else "unknown"
        self._emit("game_init", init_data)

    async def run(self, event_callback: EventCallback = None) -> Faction:
        """主循环：运行游戏直到结束。返回获胜阵营。"""
        self._event_callback = event_callback

        if not self.state:
            self.init_game()

        state = self.state

        while True:
            winner = check_winner(state)
            if winner:
                state.winner = winner
                state.phase = Phase.GAME_OVER
                self._emit("game_over", {"winner": winner.value})
                return winner

            state.turn += 1

            # --- 夜晚阶段 ---
            await self._handle_night()

            winner = check_winner(state)
            if winner:
                state.winner = winner
                state.phase = Phase.GAME_OVER
                self._emit("game_over", {"winner": winner.value, "note": "夜晚阶段后判定"})
                return winner

            # --- 白天阶段 ---
            await self._handle_day()

            # 周期性压缩 agent memory
            await self._summarize_all()

    # ============================================================
    # 夜晚阶段
    # ============================================================

    async def _handle_night(self):
        state = self.state
        state.phase = Phase.NIGHT_WOLF
        self._emit("night_start", {"turn": state.turn})

        order = get_night_order(state)

        for phase in order:
            state.phase = phase
            handler = {
                Phase.NIGHT_WOLF: self._night_wolf,
                Phase.NIGHT_WITCH: self._night_witch,
                Phase.NIGHT_SEER: self._night_seer,
                Phase.NIGHT_HUNTER: self._night_hunter,
                Phase.NIGHT_FOOL: self._night_fool,
            }.get(phase)
            if handler:
                await handler()

    async def _night_wolf(self):
        """狼人行动：各狼人独立投票，多数决。"""
        state = self.state
        alive_wolves = state.get_alive_wolves()

        if not alive_wolves:
            self._emit("wolf_action", {"decision": None, "reason": "无存活狼人"})
            return

        wolf_votes = {}
        for wolf in alive_wolves:
            result = await self._get_decision(wolf.player_id, "KILL", {
                "phase": "NIGHT_WOLF",
                "alive_wolves": [w.player_id for w in alive_wolves],
            })
            wolf_votes[wolf.player_id] = result.target_id

        target = resolve_wolf_votes(wolf_votes)

        if target is None:
            state.wolf_target = None
            self._emit("wolf_action", {"decision": "SKIP", "reason": "空刀"})
        else:
            state.wolf_target = target
            self._emit("wolf_action", {"target": target})

    async def _night_witch(self):
        """女巫行动：先看死者，再决定用药。"""
        state = self.state
        witch_list = state.get_alive_by_role(Role.WITCH)

        if not witch_list:
            return
        witch = witch_list[0]

        # 告知死者
        dead_id = state.wolf_target
        if witch.witch_knows_dead:
            msg = f"[系统] 今夜 {dead_id} 号玩家死亡" if dead_id else "[系统] 今夜是平安夜"
            self._send_to_agent(witch.player_id, msg)

        # 用药决策
        if witch.witch_save_available or witch.witch_poison_available:
            result = await self._get_decision(witch.player_id, "WITCH_ACTION", {
                "phase": "NIGHT_WITCH",
                "dead_player": dead_id,
                "save_available": witch.witch_save_available,
                "poison_available": witch.witch_poison_available,
            })

            # 同晚不能用两种药
            if result.action == "SAVE" and result.action == "POISON":
                # LLM 同时返回两种 → 随机选一种
                if random.random() < 0.5:
                    result = result.__class__(action="SAVE", target_id=0, speech="", raw_response=result.raw_response)
                else:
                    result = result.__class__(action="POISON", target_id=result.target_id, speech="", raw_response=result.raw_response)

            if result.action == "SAVE" and witch.witch_save_available:
                target = state.wolf_target
                if target:
                    state.witch_saved = target
                    witch.witch_save_available = False
                    msg = f"[系统] 你使用了解药救了 {target} 号" if target != witch.player_id else "[系统] 你使用了解药自救"
                    self._send_to_agent(witch.player_id, msg)

            elif result.action == "POISON" and witch.witch_poison_available:
                valid, _ = validate_action(state, witch.player_id, "POISON", result.target_id)
                if valid:
                    state.witch_poisoned = result.target_id
                    witch.witch_poison_available = False
                    self._send_to_agent(witch.player_id, f"[系统] 你毒杀了 {result.target_id} 号")

        # 解药用完后不再获知死者
        if not witch.witch_save_available:
            witch.witch_knows_dead = False

    async def _night_seer(self):
        """预言家查验。"""
        state = self.state
        seer_list = state.get_alive_by_role(Role.SEER)
        if not seer_list:
            return
        seer = seer_list[0]

        result = await self._get_decision(seer.player_id, "CHECK", {"phase": "NIGHT_SEER"})

        if result.action == "CHECK" and result.target_id > 0:
            valid, _ = validate_action(state, seer.player_id, "CHECK", result.target_id)
            if valid:
                state.seer_checked = result.target_id
                target = state.get_player(result.target_id)
                is_good = target.is_good
                state.seer_result = is_good
                result_text = "好人" if is_good else "狼人"
                self._send_to_agent(seer.player_id, f"[系统] 查验 {result.target_id} 号：{result_text}")

    async def _night_hunter(self):
        """猎人确认状态。"""
        state = self.state
        hunter_list = state.get_alive_by_role(Role.HUNTER)
        if not hunter_list:
            return
        hunter = hunter_list[0]
        self._send_to_agent(
            hunter.player_id,
            f"[系统] 开枪状态：{'可开枪' if hunter.hunter_can_shoot else '不可开枪'}"
        )

    async def _night_fool(self):
        """白痴确认身份（仅首夜）。"""
        state = self.state
        fool_list = state.get_alive_by_role(Role.FOOL)
        if not fool_list:
            return
        fool = fool_list[0]
        self._send_to_agent(
            fool.player_id,
            "[系统] 你是白痴，被放逐时翻牌免死，但丧失投票权"
        )

    # ============================================================
    # 白天阶段
    # ============================================================

    async def _handle_day(self):
        state = self.state

        # 1. 天亮通报
        await self._day_announce()

        # 2. 警长竞选（仅第 1 天）
        if state.turn == 1 and not state.sheriff_elected:
            await self._election()

        # 3. 遗言
        await self._last_words()

        # 4. 发言
        state.phase = Phase.DAY_SPEECH
        await self._speech_round()

        # 5. 投票
        state.phase = Phase.DAY_VOTE
        await self._vote_round()

        # 6. 处理投票结果
        await self._resolve_vote()

    async def _day_announce(self):
        """天亮通报死讯。"""
        state = self.state
        state.phase = Phase.DAY_ANNOUNCE

        # 计算实际死亡
        deaths = []
        wolf_target = state.wolf_target

        # 女巫解药判定
        if state.witch_saved == wolf_target:
            wolf_target = None

        # 狼刀死亡
        if wolf_target:
            deaths.append((wolf_target, "狼刀"))
            state.kill_player(wolf_target, "狼刀")

        # 女巫毒杀
        if state.witch_poisoned:
            deaths.append((state.witch_poisoned, "毒杀"))
            state.kill_player(state.witch_poisoned, "毒杀")
            poisoned = state.get_player(state.witch_poisoned)
            if poisoned and poisoned.role == Role.HUNTER:
                poisoned.hunter_can_shoot = False

        if not deaths:
            state.add_public_log("昨夜是平安夜")
        else:
            for pid, cause in deaths:
                state.add_public_log(f"昨夜 {pid} 号玩家死亡")

        self._emit("day_announce", {
            "deaths": [d[0] for d in deaths],
            "peaceful": len(deaths) == 0,
        })

        # 广播到所有 agent
        if deaths:
            death_msg = "昨夜死亡：" + "、".join(f"{pid}号" for pid, _ in deaths)
        else:
            death_msg = "昨夜是平安夜"
        self._broadcast_to_agents(death_msg)

        # 重置夜晚状态
        state.wolf_target = None
        state.witch_saved = None
        state.witch_poisoned = None
        state.seer_checked = None
        state.seer_result = None

    async def _last_words(self):
        """遗言环节（第一夜死者有遗言）。"""
        state = self.state
        if state.turn > 1:
            return

        for player in state.players:
            if not player.alive:
                speech = await self._get_speech(player.player_id, {
                    "phase": "LAST_WORDS",
                    "note": "你在昨夜死亡，这是你的遗言",
                })
                if speech:
                    state.add_public_log(f"{player.player_id} 号遗言：{speech}")
                    self._broadcast_to_agents(f"[遗言] {player.player_id}号：{speech}")

    async def _election(self):
        """警长竞选。"""
        state = self.state
        state.phase = Phase.DAY_ELECTION

        candidates = list(state.get_alive_ids())
        num_candidates = random.randint(2, min(4, len(candidates)))
        candidates = random.sample(candidates, num_candidates)

        if not candidates:
            self._emit("election", {"sheriff_id": None, "reason": "无人竞选"})
            return

        self._emit("election_start", {"candidates": candidates})
        self._broadcast_to_agents(
            f"警长竞选开始，候选人：{'、'.join(f'{c}号' for c in candidates)}"
        )

        # 投票
        voters = [p for p in state.get_alive_players() if p.player_id not in candidates]
        votes = {}
        for voter in voters:
            result = await self._get_decision(voter.player_id, "VOTE_ELECTION", {
                "candidates": candidates,
            })
            if result.target_id and result.target_id in candidates:
                votes[voter.player_id] = result.target_id

        sheriff_id = resolve_election(votes, candidates)

        if sheriff_id:
            state.sheriff_id = sheriff_id
            state.sheriff_elected = True
            self._emit("election", {"sheriff_id": sheriff_id})
            self._broadcast_to_agents(f"{sheriff_id} 号玩家当选警长")
        else:
            self._emit("election", {"sheriff_id": None, "reason": "平票"})
            self._broadcast_to_agents("警长竞选平票，本局无警长")

    async def _speech_round(self):
        """发言轮。按顺序让每个存活玩家发言。"""
        state = self.state
        alive = state.get_alive_ids()

        # 确定发言顺序
        if state.sheriff_id and state.sheriff_id in alive:
            direction = "left"
            idx = alive.index(state.sheriff_id)
            order = alive[idx + 1:] + alive[:idx] if direction == "left" else alive[idx - 1::-1] + alive[:idx - 1:-1]
        else:
            order = alive

        state.speech_order = order

        for speaker_id in order:
            state.current_speaker = speaker_id
            self._emit("speech_turn", {"player_id": speaker_id})

            speech = await self._get_speech(speaker_id, {
                "phase": "DAY_SPEECH",
                "turn": state.turn,
            })
            if speech:
                state.add_public_log(f"{speaker_id} 号发言：{speech}")
                self._broadcast_to_agents(f"[发言] {speaker_id}号：{speech}")

    async def _vote_round(self):
        """投票放逐轮。"""
        state = self.state
        voters = state.get_voters()
        votes = {}

        self._broadcast_to_agents("投票开始，请选择你要放逐的玩家。")

        for voter in voters:
            result = await self._get_decision(voter.player_id, "VOTE", {})
            if result.target_id:
                votes[voter.player_id] = result.target_id

        result = tally_votes(votes, state.sheriff_id)
        state.vote_result = result["counts"]

        if result["is_tie"]:
            # 平票 → PK
            state.pk_candidates = result["tied_players"]
            state.phase = Phase.DAY_PK_SPEECH
            self._emit("vote_tie", {"tied_players": result["tied_players"]})
            self._broadcast_to_agents(
                f"投票平票！PK 候选人：{'、'.join(f'{c}号' for c in result['tied_players'])}"
            )

            # PK 发言
            for pid in state.pk_candidates:
                state.current_speaker = pid
                self._emit("speech_turn", {"player_id": pid, "pk": True})
                speech = await self._get_speech(pid, {
                    "phase": "DAY_PK_SPEECH",
                })
                if speech:
                    state.add_public_log(f"{pid} 号 PK 发言：{speech}")
                    self._broadcast_to_agents(f"[PK发言] {pid}号：{speech}")

            # PK 投票
            state.phase = Phase.DAY_PK_VOTE
            pk_voters = [v for v in voters if v.player_id not in state.pk_candidates]
            pk_votes = {}
            for voter in pk_voters:
                result = await self._get_decision(voter.player_id, "VOTE", {
                    "pk_candidates": state.pk_candidates,
                })
                if result.target_id and result.target_id in state.pk_candidates:
                    pk_votes[voter.player_id] = result.target_id

            pk_result = tally_votes(pk_votes, state.sheriff_id)
            if pk_result["is_tie"]:
                self._emit("vote_result", {"eliminated": None, "reason": "平票"})
                self._broadcast_to_agents("PK 投票仍然平票，无人被放逐。")
                return
            else:
                eliminated = pk_result["top"][0]
        else:
            eliminated = result["top"][0]

        state.eliminated_today = eliminated
        self._emit("vote_result", {"eliminated": eliminated})

        # 执行放逐
        eliminated_player = state.get_player(eliminated)
        if eliminated_player.role == Role.FOOL and not eliminated_player.fool_revealed:
            eliminated_player.fool_revealed = True
            eliminated_player.has_vote = False
            state.add_public_log(f"{eliminated} 号翻牌为白痴，免死但丧失投票权")
            self._broadcast_to_agents(f"{eliminated} 号被放逐，翻牌为白痴！免死但丧失投票权。")
            self._emit("fool_revealed", {"player_id": eliminated})
        else:
            state.kill_player(eliminated, "放逐")
            self._broadcast_to_agents(f"{eliminated} 号被放逐出局。")

            # 猎人开枪
            if eliminated_player.role == Role.HUNTER and eliminated_player.hunter_can_shoot:
                result = await self._get_decision(eliminated, "SHOOT", {
                    "phase": "HUNTER_DEATH",
                })
                if result.action == "SHOOT" and result.target_id > 0:
                    target = state.get_player(result.target_id)
                    if target and target.alive:
                        state.kill_player(result.target_id, "猎人开枪")
                        self._broadcast_to_agents(f"猎人开枪带走了 {result.target_id} 号！")
                        self._emit("hunter_shoot", {"target": result.target_id})

            # 警长移交
            if eliminated == state.sheriff_id:
                result = await self._get_decision(eliminated, "GIVE_BADGE", {})
                if result.action == "GIVE_BADGE" and result.target_id > 0:
                    target = state.get_player(result.target_id)
                    if target and target.alive:
                        state.sheriff_id = result.target_id
                        self._broadcast_to_agents(f"警长将警徽移交给了 {result.target_id} 号。")
                    else:
                        state.sheriff_id = None
                        self._broadcast_to_agents("警徽被撕毁，本局不再有警长。")

    async def _resolve_vote(self):
        """处理投票后的收尾。"""
        state = self.state
        state.phase = Phase.DAY_SPEECH
        state.eliminated_today = None
        state.pk_candidates = []
        state.vote_result = {}
        state.speech_order = []
        state.current_speaker = None

    # ============================================================
    # LLM 交互
    # ============================================================

    async def _ask_llm(self, player_id: int, action_hint: str, context: dict):
        """请求 LLM 决策。委托给 PlayerAgent.decide()。"""
        from ..agent.parser import ActionResult
        agent = self._agents.get(player_id)
        if not agent:
            return ActionResult(action="SKIP", target_id=0, speech="", raw_response="[NO AGENT]")
        return await agent.decide(action_hint, context)

    async def _ask_llm_speech(self, player_id: int, context: dict) -> str:
        """请求 LLM 发言。委托给 PlayerAgent.speak()。"""
        agent = self._agents.get(player_id)
        if not agent:
            return ""
        return await agent.speak(context)

    def _send_to_agent(self, player_id: int, msg: str):
        """向单个 agent 发送私密消息。"""
        agent = self._agents.get(player_id)
        if agent:
            agent.observe(msg)

    def _broadcast_to_agents(self, msg: str):
        """向所有 agent 广播公开消息。"""
        for agent in self._agents.values():
            agent.observe(msg)

    async def _summarize_all(self):
        """触发所有 agent 的 memory 压缩。"""
        for agent in self._agents.values():
            await agent.summarize()

    def _emit(self, event_type: str, data: dict):
        """触发事件回调。通过 asyncio.create_task 异步推送，不阻塞游戏主循环。"""
        if self._event_callback:
            asyncio.create_task(self._event_callback(event_type, data))

    # ============================================================
    # 人类输入（God 模式 / Player 模式）
    # ============================================================

    def resolve_human_decision(self, decision: dict) -> None:
        """接收人类决策，唤醒暂停的游戏循环。"""
        self._human_decision = decision
        self._human_input_event.set()

    async def _get_decision(self, player_id: int, action_hint: str, context: dict):
        """获取决策：God/Player 模式等人类输入，auto 模式调 LLM。"""
        if self._mode == "god":
            return await self._wait_for_human(player_id, action_hint, context)
        elif self._mode == "player" and player_id == self._human_player_id:
            return await self._wait_for_human(player_id, action_hint, context)
        else:
            return await self._ask_llm(player_id, action_hint, context)

    async def _get_speech(self, player_id: int, context: dict) -> str:
        """获取发言：God/Player 模式等人类输入，auto 模式调 LLM。"""
        if self._mode == "god":
            result = await self._wait_for_human(player_id, "SPEECH", context)
            return result.speech or ""
        elif self._mode == "player" and player_id == self._human_player_id:
            result = await self._wait_for_human(player_id, "SPEECH", context)
            return result.speech or ""
        else:
            return await self._ask_llm_speech(player_id, context)

    async def _wait_for_human(self, player_id: int, action_hint: str,
                              context: dict):
        """暂停游戏循环，等待人类通过 WebSocket 发送决策。"""
        from ..agent.parser import ActionResult

        state = self.state
        valid_targets = self._compute_valid_targets(player_id, action_hint, context)

        role_str = "unknown"
        player = state.get_player(player_id)
        if player:
            role_str = player.role.value

        self._emit("request_input", {
            "player_id": player_id,
            "action_hint": action_hint,
            "context": context,
            "valid_targets": valid_targets,
            "role": role_str,
        })

        self._human_input_event.clear()
        await self._human_input_event.wait()

        decision = self._human_decision or {}
        self._human_decision = None

        action = decision.get("action", action_hint if action_hint != "SPEECH" else "SKIP")
        target_id = decision.get("target_id", 0)
        if isinstance(target_id, str):
            try:
                target_id = int(target_id)
            except ValueError:
                target_id = 0

        return ActionResult(
            action=action,
            target_id=target_id,
            speech=decision.get("speech", ""),
            raw_response=json.dumps(decision),
        )

    def _compute_valid_targets(self, player_id: int, action_hint: str,
                                context: dict) -> list[int]:
        """根据行动类型计算可选目标列表。"""
        state = self.state
        if action_hint in ("KILL", "CHECK", "POISON", "SHOOT"):
            return [p.player_id for p in state.get_alive_players()
                    if p.player_id != player_id]
        elif action_hint == "VOTE":
            pk = context.get("pk_candidates", [])
            if pk:
                return pk
            return state.get_alive_ids()
        elif action_hint == "VOTE_ELECTION":
            return context.get("candidates", [])
        elif action_hint == "GIVE_BADGE":
            return [p.player_id for p in state.get_alive_players()
                    if p.player_id != player_id]
        elif action_hint in ("SPEECH", "LAST_WORDS"):
            return []
        elif action_hint == "WITCH_ACTION":
            return state.get_alive_ids()
        return state.get_alive_ids()
