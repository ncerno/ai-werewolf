"""序列化器单元测试。"""
import pytest
from src.engine.state import GameState, Player, Role, Faction, Phase
from src.server.serializer import (
    serialize_player,
    serialize_game_state,
    get_phase_name,
)


def make_player(pid: int, role: Role, alive: bool = True) -> Player:
    p = Player(player_id=pid, role=role, alive=alive)
    if role == Role.WITCH:
        p.witch_save_available = True
        p.witch_poison_available = True
    if role == Role.HUNTER:
        p.hunter_can_shoot = True
    return p


def make_state(roles: list[Role]) -> GameState:
    players = [make_player(i + 1, role) for i, role in enumerate(roles)]
    return GameState(players=players)


class TestSerializePlayer:
    def test_reveal_role_true(self):
        p = make_player(1, Role.WEREWOLF)
        data = serialize_player(p, True)
        assert data["role"] == "werewolf"

    def test_reveal_role_false_alive(self):
        p = make_player(1, Role.WEREWOLF, alive=True)
        data = serialize_player(p, False)
        assert data["role"] == "unknown"

    def test_dead_player_always_reveals_role(self):
        p = make_player(1, Role.SEER, alive=False)
        data = serialize_player(p, False)
        assert data["role"] == "seer"

    def test_includes_basic_fields(self):
        p = make_player(3, Role.VILLAGER)
        data = serialize_player(p, True)
        assert data["player_id"] == 3
        assert data["alive"] is True
        assert data["has_vote"] is True
        assert "is_sheriff" in data

    def test_no_vote_player(self):
        p = make_player(5, Role.FOOL)
        p.has_vote = False
        data = serialize_player(p, True)
        assert data["has_vote"] is False


class TestSerializeGameState:
    def test_spectator_hides_alive_roles(self):
        s = make_state([Role.WEREWOLF, Role.SEER, Role.VILLAGER])
        data = serialize_game_state(s, "spectator")
        assert data["players"][0]["role"] == "unknown"  # alive werewolf
        assert data["players"][1]["role"] == "unknown"  # alive seer

    def test_spectator_reveals_dead_roles(self):
        s = make_state([Role.WEREWOLF, Role.SEER, Role.VILLAGER])
        s.kill_player(1)
        data = serialize_game_state(s, "spectator")
        assert data["players"][0]["role"] == "werewolf"  # dead

    def test_god_sees_all_roles(self):
        s = make_state([Role.WEREWOLF, Role.SEER, Role.VILLAGER])
        data = serialize_game_state(s, "god")
        assert data["players"][0]["role"] == "werewolf"
        assert data["players"][1]["role"] == "seer"
        assert data["players"][2]["role"] == "villager"

    def test_player_perspective_sees_own_role(self):
        s = make_state([Role.WEREWOLF, Role.SEER, Role.VILLAGER])
        data = serialize_game_state(s, "player_2")
        # player 2 sees own role
        assert data["players"][1]["role"] == "seer"
        # but not others
        assert data["players"][0]["role"] == "unknown"
        assert data["players"][2]["role"] == "unknown"

    def test_includes_game_info(self):
        s = make_state([Role.WEREWOLF, Role.SEER, Role.VILLAGER])
        s.turn = 3
        s.phase = Phase.DAY_SPEECH
        s.sheriff_id = 2
        s.sheriff_elected = True
        s.current_speaker = 1
        s.speech_order = [1, 2, 3]

        data = serialize_game_state(s, "spectator")
        assert data["turn"] == 3
        assert data["phase"] == "DAY_SPEECH"
        assert data["sheriff_id"] == 2
        assert data["sheriff_elected"] is True
        assert data["current_speaker"] == 1
        assert data["alive_count"] == 3

    def test_sheriff_badge_on_player(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF, Role.SEER])
        s.sheriff_id = 2
        data = serialize_game_state(s, "god")
        assert data["players"][1]["is_sheriff"] is True
        assert data["players"][0]["is_sheriff"] is False

    def test_winner_field(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER])
        s.winner = Faction.GOOD
        data = serialize_game_state(s, "spectator")
        assert data["winner"] == "good"

    def test_private_logs_god(self):
        s = make_state([Role.WEREWOLF, Role.SEER])
        s.add_private_log(1, "你是狼人")
        s.add_private_log(2, "查验结果: 1号是狼人")
        data = serialize_game_state(s, "god")
        assert "private_logs" in data
        assert "1" in data["private_logs"]
        assert "2" in data["private_logs"]

    def test_private_log_player(self):
        s = make_state([Role.WEREWOLF, Role.SEER])
        s.add_private_log(1, "你是狼人")
        s.add_private_log(2, "查验结果")
        data = serialize_game_state(s, "player_1")
        assert "private_log" in data
        assert "你是狼人" in data["private_log"][0]
        # player 1 should not see player 2's private log
        data_p2 = serialize_game_state(s, "player_2")
        assert "查验结果" in data_p2["private_log"][0]

    def test_public_log_truncated(self):
        s = make_state([Role.VILLAGER, Role.WEREWOLF])
        for i in range(60):
            s.add_public_log(f"日志 {i}")
        data = serialize_game_state(s, "spectator")
        assert len(data["public_log"]) <= 50

    def test_game_over_phase_name(self):
        s = make_state([Role.WEREWOLF, Role.VILLAGER])
        s.phase = Phase.GAME_OVER
        s.winner = Faction.WOLF
        data = serialize_game_state(s, "spectator")
        assert data["phase_name"] == "游戏结束"
        assert data["winner"] == "wolf"


class TestGetPhaseName:
    def test_all_phases_have_name(self):
        for phase in Phase:
            name = get_phase_name(phase)
            assert isinstance(name, str)
            assert len(name) > 0

    def test_night_phases(self):
        assert "狼" in get_phase_name(Phase.NIGHT_WOLF)
        assert "女巫" in get_phase_name(Phase.NIGHT_WITCH)
        assert "预言" in get_phase_name(Phase.NIGHT_SEER)

    def test_day_phases(self):
        assert "天亮" in get_phase_name(Phase.DAY_ANNOUNCE)
        assert "竞选" in get_phase_name(Phase.DAY_ELECTION)
        assert "发言" in get_phase_name(Phase.DAY_SPEECH)
        assert "投票" in get_phase_name(Phase.DAY_VOTE)
