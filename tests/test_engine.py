"""游戏规则引擎单元测试。"""
import pytest
from src.engine.state import GameState, Player, Role, Faction, Phase
from src.engine.rules import (
    check_winner,
    validate_action,
    tally_votes,
    resolve_wolf_votes,
    resolve_election,
    get_night_order,
)


def make_player(pid: int, role: Role, alive: bool = True) -> Player:
    p = Player(player_id=pid, role=role, alive=alive)
    if role == Role.WITCH:
        p.witch_save_available = True
        p.witch_poison_available = True
        p.witch_knows_dead = True
    if role == Role.HUNTER:
        p.hunter_can_shoot = True
    return p


def make_state(roles: list[Role]) -> GameState:
    """从角色列表创建状态。"""
    players = [make_player(i + 1, role) for i, role in enumerate(roles)]
    return GameState(players=players)


class TestCheckWinner:
    def test_good_wins_all_wolves_dead(self):
        """所有狼人死亡 → 好人胜"""
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        s.kill_player(1)
        assert check_winner(s) == Faction.GOOD

    def test_wolf_wins_by_numbers(self):
        """狼数 >= 好人数 → 狼人胜"""
        s = make_state([Role.WEREWOLF, Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        s.kill_player(3)
        assert check_winner(s) == Faction.WOLF

    def test_wolf_wins_all_gods_dead(self):
        """屠边：所有神出局 → 狼人胜"""
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER, Role.WITCH])
        s.kill_player(3)  # seer
        s.kill_player(4)  # witch
        assert check_winner(s) == Faction.WOLF

    def test_wolf_wins_all_villagers_dead(self):
        """屠边：所有平民出局 → 狼人胜"""
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        s.kill_player(2)  # villager
        assert check_winner(s) == Faction.WOLF

    def test_game_continues(self):
        """游戏继续：双方都有存活"""
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER, Role.WITCH])
        assert check_winner(s) is None


class TestValidateAction:
    def test_kill_valid(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        ok, msg = validate_action(s, 1, "KILL", 2)
        assert ok

    def test_kill_not_wolf(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        ok, msg = validate_action(s, 2, "KILL", 1)
        assert not ok

    def test_kill_wolf_companion(self):
        s = make_state([Role.WEREWOLF, Role.WEREWOLF, Role.VILLAGER])
        ok, msg = validate_action(s, 1, "KILL", 2)
        assert not ok

    def test_kill_self_allowed(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER])
        ok, msg = validate_action(s, 1, "KILL", 1)
        assert ok  # 自刀允许

    def test_kill_dead_target(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        s.kill_player(2)
        ok, msg = validate_action(s, 1, "KILL", 2)
        assert not ok

    def test_check_valid(self):
        s = make_state([Role.SEER, Role.WEREWOLF])
        ok, msg = validate_action(s, 1, "CHECK", 2)
        assert ok

    def test_check_not_seer(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF])
        ok, msg = validate_action(s, 1, "CHECK", 2)
        assert not ok

    def test_vote_valid(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF])
        ok, msg = validate_action(s, 1, "VOTE", 2)
        assert ok

    def test_vote_no_right(self):
        s = make_state([Role.FOOL, Role.WEREWOLF])
        s.players[0].has_vote = False
        ok, msg = validate_action(s, 1, "VOTE", 2)
        assert not ok

    def test_save_valid(self):
        s = make_state([Role.WITCH, Role.VILLAGER])
        ok, msg = validate_action(s, 1, "SAVE", 0)
        assert ok

    def test_save_already_used(self):
        s = make_state([Role.WITCH, Role.VILLAGER])
        s.players[0].witch_save_available = False
        ok, msg = validate_action(s, 1, "SAVE", 0)
        assert not ok

    def test_poison_valid(self):
        s = make_state([Role.WITCH, Role.VILLAGER])
        ok, msg = validate_action(s, 1, "POISON", 2)
        assert ok

    def test_poison_already_used(self):
        s = make_state([Role.WITCH, Role.VILLAGER])
        s.players[0].witch_poison_available = False
        ok, msg = validate_action(s, 1, "POISON", 2)
        assert not ok

    def test_shoot_valid(self):
        s = make_state([Role.HUNTER, Role.WEREWOLF])
        ok, msg = validate_action(s, 1, "SHOOT", 2)
        assert ok

    def test_shoot_not_hunter(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF])
        ok, msg = validate_action(s, 1, "SHOOT", 2)
        assert not ok

    def test_unknown_action(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF])
        ok, msg = validate_action(s, 1, "UNKNOWN", 0)
        assert not ok

    def test_pk_vote_only_pk_candidates(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF, Role.SEER])
        s.phase = Phase.DAY_PK_VOTE
        s.pk_candidates = [1, 2]
        ok, _ = validate_action(s, 3, "VOTE", 1)
        assert ok
        ok, _ = validate_action(s, 3, "VOTE", 3)
        assert not ok


class TestTallyVotes:
    def test_simple_majority(self):
        # 1,2,3 投 5; 4 投 6 → 5 得 3 票, 6 得 1 票
        votes = {1: 5, 2: 5, 3: 5, 4: 6}
        result = tally_votes(votes)
        assert result["top"] == [5]
        assert not result["is_tie"]

    def test_tie(self):
        # 1,2 投 3; 3,4 投 5 → 各 2 票, 平票
        votes = {1: 3, 2: 3, 3: 5, 4: 5}
        result = tally_votes(votes)
        assert result["is_tie"]
        assert set(result["tied_players"]) == {3, 5}

    def test_sheriff_1_5_votes(self):
        votes = {1: 2, 2: 2, 3: 3}  # voter 3 is sheriff
        result = tally_votes(votes, sheriff_id=3)
        assert result["top"] == [2]  # 1.5 > 1.0

    def test_empty_votes(self):
        result = tally_votes({})
        assert result["top"] == []
        assert not result["is_tie"]


class TestResolveWolfVotes:
    def test_majority(self):
        votes = {1: 5, 2: 5, 3: 6, 4: 6}
        assert resolve_wolf_votes(votes) == 6

    def test_tie_random(self):
        votes = {1: 5, 2: 5}
        result = resolve_wolf_votes(votes)
        assert result in [5, None]  # tie → random or skip

    def test_all_skip(self):
        votes = {1: 0, 2: 0, 3: 0}
        assert resolve_wolf_votes(votes) is None

    def test_partial_skip(self):
        votes = {1: 0, 2: 5, 3: 6, 4: 6}
        assert resolve_wolf_votes(votes) == 6


class TestResolveElection:
    def test_majority(self):
        # 1,2 投 3; 4 投 4 → 3 得 2 票, 4 得 1 票, 3 当选
        votes = {1: 3, 2: 3, 4: 4}
        result = resolve_election(votes, [3, 4])
        assert result == 3

    def test_tie(self):
        votes = {1: 3, 2: 4, 5: 3, 6: 4}
        result = resolve_election(votes, [3, 4])
        assert result is None

    def test_no_candidates(self):
        votes = {}
        result = resolve_election(votes, [])
        assert result is None


class TestGameState:
    def test_get_alive(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        s.kill_player(1)
        assert len(s.get_alive_players()) == 2
        assert s.get_player(1).alive is False

    def test_get_by_faction(self):
        s = make_state([Role.WEREWOLF, Role.WEREWOLF, Role.VILLAGER, Role.SEER])
        assert len(s.get_alive_by_faction(Faction.WOLF)) == 2
        assert len(s.get_alive_by_faction(Faction.GOOD)) == 2

    def test_get_voters(self):
        s = make_state([Role.VILLAGER, Role.FOOL])
        s.players[1].has_vote = False
        voters = s.get_voters()
        assert len(voters) == 1


class TestGetNightOrder:
    def test_first_turn_includes_fool(self):
        s = make_state([Role.WEREWOLF] * 4 + [Role.SEER, Role.WITCH, Role.HUNTER, Role.FOOL] + [Role.VILLAGER] * 4)
        s.turn = 1
        order = get_night_order(s)
        assert Phase.NIGHT_FOOL in order

    def test_later_turns_no_fool(self):
        s = make_state([Role.WEREWOLF] * 4 + [Role.SEER, Role.WITCH, Role.HUNTER, Role.FOOL] + [Role.VILLAGER] * 4)
        s.turn = 3
        order = get_night_order(s)
        assert Phase.NIGHT_FOOL not in order
