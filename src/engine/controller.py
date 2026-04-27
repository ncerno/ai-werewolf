"""游戏控制器：回合调度、阶段推进、事件回调。"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from .state import GameState, Phase, Player, Role, Faction
from .rules import (
    check_winner,
    get_night_order,
    resolve_wolf_votes,
    resolve_election,
    tally_votes,
)

EventCallback = Callable[[str, dict], Awaitable[None]]


def create_players() -> list[Player]:
    """创建标准 12 人局玩家列表。"""
    roles = [
        Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF,
        Role.SEER, Role.WITCH, Role.HUNTER, Role.FOOL,
        Role.VILLAGER, Role.VILLAGER, Role.VILLAGER, Role.VILLAGER,
    ]
    import random
    random.shuffle(roles)

    players = []
    for i, role in enumerate(roles, 1):
        p = Player(player_id=i, role=role)
        if role == Role.WITCH:
            p.witch_save_available = True
            p.witch_poison_available = True
            p.witch_knows_dead = True
        if role == Role.HUNTER:
            p.hunter_can_shoot = True  # 初始可用，被毒后设为 False
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
        self._mode: str = "auto"  # auto / god / player

    # ============================================================
    # 游戏生命周期
    # ============================================================

    def init_game(self, mode: str = "auto"):
        """初始化新游戏。"""
        import random
        players = create_players()
        self.state = GameState(players=players)
        self._mode = mode
        self._emit("game_init", {"mode": mode, "players": len(players)})

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

        # 收集各狼人投票（模拟；Phase 3 接入 LLM 后替换为异步调用）
        wolf_votes = {}
        for wolf in alive_wolves:
            decision = await self._ask_llm(wolf.player_id, "KILL", {
                "phase": "NIGHT_WOLF",
                "alive_wolves": [w.player_id for w in alive_wolves],
            })
            target_id = self._parse_decision(decision, wolf.player_id)
            wolf_votes[wolf.player_id] = target_id

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
        witch = state.get_alive_by_role(Role.WITCH)

        if not witch:
            return
        witch = witch[0]

        # 告知死者
        dead_id = state.wolf_target
        if witch.witch_knows_dead:
            msg = f"今夜 {dead_id} 号玩家死亡" if dead_id else "今夜是平安夜"
            state.add_private_log(witch.player_id, msg)

        # 用药决策
        if witch.witch_save_available or witch.witch_poison_available:
            decision = await self._ask_llm(witch.player_id, "WITCH_ACTION", {
                "phase": "NIGHT_WITCH",
                "dead_player": dead_id,
                "save_available": witch.witch_save_available,
                "poison_available": witch.witch_poison_available,
            })
            # 解析女巫行动
            self._parse_witch_action(decision, witch)

    def _parse_witch_action(self, decision: str, witch: Player):
        """解析女巫的用药决策。"""
        state = self.state
        decision_upper = decision.upper().strip()

        # 同晚不能使用两种药
        has_save = "SAVE" in decision_upper
        has_poison = "POISON" in decision_upper

        if has_save and has_poison:
            # 规则：同晚不能用两种药，随机选一种
            import random
            if random.random() < 0.5:
                has_poison = False
            else:
                has_save = False

        if has_save and witch.witch_save_available:
            target = state.wolf_target
            if target == witch.player_id:
                # 女巫自救
                state.witch_saved = target
                witch.witch_save_available = False
                state.add_private_log(witch.player_id, "你使用了解药自救")
            elif target:
                state.witch_saved = target
                witch.witch_save_available = False
                state.add_private_log(witch.player_id, f"你使用了解药救了 {target} 号")

        if has_poison and witch.witch_poison_available:
            # 提取毒药目标
            import re
            m = re.search(r'POISON\s*(\d+)', decision_upper)
            if m:
                target_id = int(m.group(1))
                valid, _ = __import__('src.engine.rules', fromlist=['validate_action']).validate_action(
                    state, witch.player_id, "POISON", target_id
                )
                if valid:
                    state.witch_poisoned = target_id
                    witch.witch_poison_available = False
                    state.add_private_log(witch.player_id, f"你毒杀了 {target_id} 号")

        # 解药用完后不再获知死者
        if not witch.witch_save_available:
            witch.witch_knows_dead = False

    async def _night_seer(self):
        """预言家查验。"""
        state = self.state
        seer = state.get_alive_by_role(Role.SEER)
        if not seer:
            return
        seer = seer[0]

        decision = await self._ask_llm(seer.player_id, "CHECK", {
            "phase": "NIGHT_SEER",
        })
        self._parse_seer_action(decision, seer)

    def _parse_seer_action(self, decision: str, seer: Player):
        import re
        m = re.search(r'CHECK\s*(\d+)', decision.upper().strip())
        if not m:
            return
        target_id = int(m.group(1))
        state = self.state
        valid, _ = __import__('src.engine.rules', fromlist=['validate_action']).validate_action(
            state, seer.player_id, "CHECK", target_id
        )
        if valid:
            state.seer_checked = target_id
            target = state.get_player(target_id)
            is_good = target.is_good
            state.seer_result = is_good
            result_text = "好人" if is_good else "狼人"
            state.add_private_log(seer.player_id, f"查验 {target_id} 号：{result_text}")

    async def _night_hunter(self):
        """猎人确认状态。"""
        state = self.state
        hunter = state.get_alive_by_role(Role.HUNTER)
        if not hunter:
            return
        hunter = hunter[0]
        state.add_private_log(
            hunter.player_id,
            f"开枪状态：{'可开枪' if hunter.hunter_can_shoot else '不可开枪'}"
        )

    async def _night_fool(self):
        """白痴确认身份（仅首夜）。"""
        state = self.state
        fool = state.get_alive_by_role(Role.FOOL)
        if not fool:
            return
        fool = fool[0]
        state.add_private_log(fool.player_id, "你是白痴，被放逐时翻牌免死，但丧失投票权")

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
            wolf_target = None  # 被救活

        # 狼刀死亡
        if wolf_target:
            deaths.append((wolf_target, "狼刀"))
            state.kill_player(wolf_target, "狼刀")

        # 女巫毒杀
        if state.witch_poisoned:
            deaths.append((state.witch_poisoned, "毒杀"))
            state.kill_player(state.witch_poisoned, "毒杀")
            # 被毒杀的猎人不能开枪
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
            return  # 仅第一夜

        for player in state.players:
            if not player.alive and player.player_id not in [
                getattr(state, 'witch_poisoned', None)
            ]:
                # 被刀的死者有遗言
                pass
        # 遗言逻辑在 Phase 3 接入 LLM 后实现

    async def _election(self):
        """警长竞选。"""
        state = self.state
        state.phase = Phase.DAY_ELECTION

        # 简化流程：随机决定上警，或全部 AI 决定
        # Phase 3 接入 LLM 后让每个 AI 决定是否上警
        candidates = list(state.get_alive_ids())
        import random

        # 随机选 2-4 人上警
        num_candidates = random.randint(2, min(4, len(candidates)))
        candidates = random.sample(candidates, num_candidates)

        if not candidates:
            self._emit("election", {"sheriff_id": None, "reason": "无人竞选"})
            return

        self._emit("election_start", {"candidates": candidates})

        # 投票
        voters = [p for p in state.get_alive_players() if p.player_id not in candidates]
        votes = {}
        for voter in voters:
            decision = await self._ask_llm(voter.player_id, "VOTE_ELECTION", {
                "candidates": candidates,
            })
            target = self._parse_decision(decision, voter.player_id, candidates)
            if target:
                votes[voter.player_id] = target

        sheriff_id = resolve_election(votes, candidates)

        if sheriff_id:
            state.sheriff_id = sheriff_id
            state.sheriff_elected = True
            self._emit("election", {"sheriff_id": sheriff_id})
        else:
            # 平票，进入 PK
            # PK 后仍平票 → 无警长
            self._emit("election", {"sheriff_id": None, "reason": "平票"})

    async def _speech_round(self):
        """发言轮。按顺序让每个存活玩家发言。"""
        state = self.state
        alive = state.get_alive_ids()

        # 确定发言顺序
        if state.sheriff_id and state.sheriff_id in alive:
            direction = "left"
            # 从警长左边/右边开始（默认左）
            idx = alive.index(state.sheriff_id)
            order = alive[idx + 1:] + alive[:idx] if direction == "left" else alive[idx - 1::-1] + alive[:idx - 1:-1]
        else:
            order = alive  # 无警长按编号

        state.speech_order = order

        for speaker_id in order:
            state.current_speaker = speaker_id
            self._emit("speech_turn", {"player_id": speaker_id})
            # Phase 3 接入 LLM：让 speaker 发言
            # 发言内容通过 LLM 生成，推送到日志

    async def _vote_round(self):
        """投票放逐轮。"""
        state = self.state
        voters = state.get_voters()
        votes = {}

        for voter in voters:
            decision = await self._ask_llm(voter.player_id, "VOTE", {})
            target = self._parse_decision(decision, voter.player_id)
            if target:
                votes[voter.player_id] = target

        result = tally_votes(votes, state.sheriff_id)
        state.vote_result = result["counts"]

        if result["is_tie"]:
            # 平票 → PK
            state.pk_candidates = result["tied_players"]
            state.phase = Phase.DAY_PK_SPEECH
            self._emit("vote_tie", {"tied_players": result["tied_players"]})

            # PK 发言
            for pid in state.pk_candidates:
                state.current_speaker = pid
                self._emit("speech_turn", {"player_id": pid, "pk": True})

            # PK 投票（PK 台上的人不能投票）
            state.phase = Phase.DAY_PK_VOTE
            pk_voters = [v for v in voters if v.player_id not in state.pk_candidates]
            pk_votes = {}
            for voter in pk_voters:
                decision = await self._ask_llm(voter.player_id, "VOTE", {
                    "pk_candidates": state.pk_candidates,
                })
                target = self._parse_decision(
                    decision, voter.player_id, state.pk_candidates
                )
                if target:
                    pk_votes[voter.player_id] = target

            pk_result = tally_votes(pk_votes, state.sheriff_id)
            if pk_result["is_tie"]:
                # 仍平票 → 无人出局
                self._emit("vote_result", {"eliminated": None, "reason": "平票"})
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
            # 白痴翻牌
            eliminated_player.fool_revealed = True
            eliminated_player.has_vote = False
            state.add_public_log(f"{eliminated} 号翻牌为白痴，免死但丧失投票权")
            self._emit("fool_revealed", {"player_id": eliminated})
        else:
            state.kill_player(eliminated, "放逐")

            # 猎人开枪
            if eliminated_player.role == Role.HUNTER and eliminated_player.hunter_can_shoot:
                decision = await self._ask_llm(eliminated, "SHOOT", {
                    "phase": "HUNTER_DEATH",
                })
                import re
                m = re.search(r'SHOOT\s*(\d+)', decision.upper().strip())
                if m:
                    shoot_target = int(m.group(1))
                    if state.get_player(shoot_target) and state.get_player(shoot_target).alive:
                        state.kill_player(shoot_target, "猎人开枪")
                        self._emit("hunter_shoot", {"target": shoot_target})

            # 警长移交
            if eliminated == state.sheriff_id:
                decision = await self._ask_llm(eliminated, "GIVE_BADGE", {})
                import re
                m = re.search(r'GIVE_BADGE\s*(\d+)', decision.upper().strip())
                if m:
                    new_sheriff = int(m.group(1))
                    if state.get_player(new_sheriff) and state.get_player(new_sheriff).alive:
                        state.sheriff_id = new_sheriff
                    else:
                        state.sheriff_id = None  # 撕警徽

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
    # 辅助方法
    # ============================================================

    async def _ask_llm(self, player_id: int, action_hint: str, context: dict) -> str:
        """请求 LLM 决策。Phase 3 接入真实的 LLM 调用。

        当前返回占位值，供 Phase 2 独立测试使用。
        """
        import random
        state = self.state
        player = state.get_player(player_id)

        if action_hint == "KILL":
            alive = state.get_alive_ids()
            # 狼人不杀狼同伴
            targets = [pid for pid in alive if pid != player_id
                       and state.get_player(pid).role != Role.WEREWOLF]
            if not targets:
                return "SKIP"
            return f"KILL {random.choice(targets)}"

        if action_hint == "CHECK":
            alive = state.get_alive_ids()
            targets = [pid for pid in alive if pid != player_id]
            return f"CHECK {random.choice(targets)}"

        if action_hint in ("VOTE", "VOTE_ELECTION"):
            candidates = context.get("pk_candidates") or context.get("candidates") or state.get_alive_ids()
            targets = [pid for pid in candidates if pid != player_id]
            if not targets:
                return "SKIP"
            return f"VOTE {random.choice(targets)}"

        if action_hint == "SHOOT":
            alive = state.get_alive_ids()
            targets = [pid for pid in alive if pid != player_id]
            return f"SHOOT {random.choice(targets)}" if random.random() > 0.5 else "SKIP"

        if action_hint == "WITCH_ACTION":
            if state.wolf_target and player.witch_save_available:
                return "SAVE" if random.random() > 0.5 else "SKIP"
            return "SKIP"

        if action_hint == "GIVE_BADGE":
            alive = state.get_alive_ids()
            targets = [pid for pid in alive if pid != player_id]
            return f"GIVE_BADGE {random.choice(targets)}"

        return "SKIP"

    def _parse_decision(self, decision: str, player_id: int, allowed_targets: list[int] = None) -> int:
        """从 LLM 返回文本中提取目标 ID。"""
        import re
        decision_upper = decision.upper().strip()

        if "SKIP" in decision_upper:
            return 0

        m = re.search(r'(?:KILL|CHECK|VOTE|SHOOT|POISON|GIVE_BADGE)\s*(\d+)', decision_upper)
        if m:
            target = int(m.group(1))
            if allowed_targets is None or target in allowed_targets:
                return target

        # 随机选一个合法目标
        if allowed_targets:
            return random.choice(allowed_targets) if allowed_targets else 0
        return 0

    def _emit(self, event_type: str, data: dict):
        """触发事件回调（同步版本，供同步方法使用）。"""
        # 事件先缓存到 state，后续由 WebSocket 层拉取
        pass
