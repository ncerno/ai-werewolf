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
        self._mode: str = "auto"  # auto / god / player

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

            await self._handle_night()

            winner = check_winner(state)
            if winner:
                state.winner = winner
                state.phase = Phase.GAME_OVER
                self._emit("game_over", {"winner": winner.value, "note": "夜晚阶段后判定"})
                return winner

            await self._handle_day()

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
        state = self.state
        alive_wolves = state.get_alive_wolves()

        if not alive_wolves:
            self._emit("wolf_action", {"decision": None, "reason": "无存活狼人"})
            return

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
        state = self.state
        witch = state.get_alive_by_role(Role.WITCH)

        if not witch:
            return
        witch = witch[0]

        dead_id = state.wolf_target
        if witch.witch_knows_dead:
            msg = f"今夜 {dead_id} 号玩家死亡" if dead_id else "今夜是平安夜"
            state.add_private_log(witch.player_id, msg)

        if witch.witch_save_available or witch.witch_poison_available:
            decision = await self._ask_llm(witch.player_id, "WITCH_ACTION", {
                "phase": "NIGHT_WITCH",
                "dead_player": dead_id,
                "save_available": witch.witch_save_available,
                "poison_available": witch.witch_poison_available,
            })
            self._parse_witch_action(decision, witch)

    def _parse_witch_action(self, decision: str, witch: Player):
        state = self.state
        decision_upper = decision.upper().strip()

        has_save = "SAVE" in decision_upper
        has_poison = "POISON" in decision_upper

        if has_save and has_poison:
            import random
            if random.random() < 0.5:
                has_poison = False
            else:
                has_save = False

        if has_save and witch.witch_save_available:
            target = state.wolf_target
            if target == witch.player_id:
                state.witch_saved = target
                witch.witch_save_available = False
                state.add_private_log(witch.player_id, "你使用了解药自救")
            elif target:
                state.witch_saved = target
                witch.witch_save_available = False
                state.add_private_log(witch.player_id, f"你使用了解药救了 {target} 号")

        if has_poison and witch.witch_poison_available:
            import re
            m = re.search(r'POISON\s*(\d+)', decision_upper)
            if m:
                target_id = int(m.group(1))
                from .rules import validate_action
                valid, _ = validate_action(
                    state, witch.player_id, "POISON", target_id
                )
                if valid:
                    state.witch_poisoned = target_id
                    witch.witch_poison_available = False
                    state.add_private_log(witch.player_id, f"你毒杀了 {target_id} 号")

        if not witch.witch_save_available:
            witch.witch_knows_dead = False

    async def _night_seer(self):
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
        from .rules import validate_action
        valid, _ = validate_action(
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
        state = self.state
        fool = state.get_alive_by_role(Role.FOOL)
        if not fool:
            return
        fool = fool[0]
        state.add_private_log(fool.player_id, "你是白痴，被放逐时翻牌免死，但丧失投票权")

    async def _handle_day(self):
        state = self.state

        await self._day_announce()

        if state.turn == 1 and not state.sheriff_elected:
            await self._election()

        await self._last_words()

        state.phase = Phase.DAY_SPEECH
        await self._speech_round()

        state.phase = Phase.DAY_VOTE
        await self._vote_round()

        await self._resolve_vote()

    async def _day_announce(self):
        state = self.state
        state.phase = Phase.DAY_ANNOUNCE

        deaths = []
        wolf_target = state.wolf_target

        if state.witch_saved == wolf_target:
            wolf_target = None

        if wolf_target:
            deaths.append((wolf_target, "狼刀"))
            state.kill_player(wolf_target, "狼刀")

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

        state.wolf_target = None
        state.witch_saved = None
        state.witch_poisoned = None
        state.seer_checked = None
        state.seer_result = None

    async def _last_words(self):
        state = self.state
        if state.turn > 1:
            return

        for player in state.players:
            if not player.alive:
                pass

    async def _election(self):
        state = self.state
        state.phase = Phase.DAY_ELECTION

        candidates = list(state.get_alive_ids())
        import random

        num_candidates = random.randint(2, min(4, len(candidates)))
        candidates = random.sample(candidates, num_candidates)

        if not candidates:
            self._emit("election", {"sheriff_id": None, "reason": "无人竞选"})
            return

        self._emit("election_start", {"candidates": candidates})

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
            self._emit("election", {"sheriff_id": None, "reason": "平票"})

    async def _speech_round(self):
        state = self.state
        alive = state.get_alive_ids()

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

    async def _vote_round(self):
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
            state.pk_candidates = result["tied_players"]
            state.phase = Phase.DAY_PK_SPEECH
            self._emit("vote_tie", {"tied_players": result["tied_players"]})

            for pid in state.pk_candidates:
                state.current_speaker = pid
                self._emit("speech_turn", {"player_id": pid, "pk": True})

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
                self._emit("vote_result", {"eliminated": None, "reason": "平票"})
                return
            else:
                eliminated = pk_result["top"][0]
        else:
            eliminated = result["top"][0]

        state.eliminated_today = eliminated
        self._emit("vote_result", {"eliminated": eliminated})

        eliminated_player = state.get_player(eliminated)
        if eliminated_player.role == Role.FOOL and not eliminated_player.fool_revealed:
            eliminated_player.fool_revealed = True
            eliminated_player.has_vote = False
            state.add_public_log(f"{eliminated} 号翻牌为白痴，免死但丧失投票权")
            self._emit("fool_revealed", {"player_id": eliminated})
        else:
            state.kill_player(eliminated, "放逐")

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

            if eliminated == state.sheriff_id:
                decision = await self._ask_llm(eliminated, "GIVE_BADGE", {})
                import re
                m = re.search(r'GIVE_BADGE\s*(\d+)', decision.upper().strip())
                if m:
                    new_sheriff = int(m.group(1))
                    if state.get_player(new_sheriff) and state.get_player(new_sheriff).alive:
                        state.sheriff_id = new_sheriff
                    else:
                        state.sheriff_id = None

    async def _resolve_vote(self):
        state = self.state
        state.phase = Phase.DAY_SPEECH
        state.eliminated_today = None
        state.pk_candidates = []
        state.vote_result = {}
        state.speech_order = []
        state.current_speaker = None

    async def _ask_llm(self, player_id: int, action_hint: str, context: dict) -> str:
        import random
        state = self.state
        player = state.get_player(player_id)

        if action_hint == "KILL":
            alive = state.get_alive_ids()
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
        import re
        import random
        decision_upper = decision.upper().strip()

        if "SKIP" in decision_upper:
            return 0

        m = re.search(r'(?:KILL|CHECK|VOTE|SHOOT|POISON|GIVE_BADGE)\s*(\d+)', decision_upper)
        if m:
            target = int(m.group(1))
            if allowed_targets is None or target in allowed_targets:
                return target

        if allowed_targets:
            return random.choice(allowed_targets) if allowed_targets else 0
        return 0

    def _emit(self, event_type: str, data: dict):
        pass
