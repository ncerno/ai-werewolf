"""GameState 序列化器：将游戏状态转为 JSON 安全字典。

纯函数模块，无状态，无异步。
支持三种视角：spectator（旁观）、god（上帝）、player_{id}（玩家）。
"""
from __future__ import annotations

from ..engine.state import GameState, Player, Phase


_PHASE_NAMES: dict[Phase, str] = {
    Phase.NIGHT_WOLF: "狼人睁眼",
    Phase.NIGHT_WITCH: "女巫睁眼",
    Phase.NIGHT_SEER: "预言家睁眼",
    Phase.NIGHT_HUNTER: "猎人确认状态",
    Phase.NIGHT_FOOL: "白痴确认身份",
    Phase.DAY_ANNOUNCE: "天亮通报",
    Phase.DAY_ELECTION: "警长竞选",
    Phase.DAY_SPEECH: "发言阶段",
    Phase.DAY_VOTE: "投票放逐",
    Phase.DAY_PK_SPEECH: "PK 发言",
    Phase.DAY_PK_VOTE: "PK 投票",
    Phase.GAME_OVER: "游戏结束",
}


def get_phase_name(phase: Phase) -> str:
    return _PHASE_NAMES.get(phase, phase.name)


def serialize_player(player: Player, reveal_role: bool) -> dict:
    """序列化单个玩家。

    Args:
        player: 玩家对象
        reveal_role: 是否公开角色。死亡玩家始终公开。
    """
    role_visible = reveal_role or not player.alive
    return {
        "player_id": player.player_id,
        "alive": player.alive,
        "role": player.role.value if role_visible else "unknown",
        "has_vote": player.has_vote,
        "is_sheriff": False,  # 由调用方覆盖
    }


def serialize_game_state(state: GameState, perspective: str = "spectator") -> dict:
    """序列化完整游戏状态。

    Args:
        state: 游戏状态对象
        perspective: 视角
            - "spectator": 旁观模式，隐藏存活角色
            - "god": 上帝模式，全部可见
            - "player_{id}": 玩家视角（如 "player_3"）

    Returns:
        JSON 安全的字典
    """
    reveal_all = perspective == "god"

    player_id = None
    if perspective.startswith("player_"):
        try:
            player_id = int(perspective.split("_", 1)[1])
        except (ValueError, IndexError):
            pass

    players = []
    for p in state.players:
        reveal = reveal_all or (player_id is not None and p.player_id == player_id)
        pdata = serialize_player(p, reveal)
        if p.player_id == state.sheriff_id:
            pdata["is_sheriff"] = True
        players.append(pdata)

    result = {
        "turn": state.turn,
        "phase": state.phase.name,
        "phase_name": get_phase_name(state.phase),
        "winner": state.winner.value if state.winner else None,
        "sheriff_id": state.sheriff_id,
        "sheriff_elected": state.sheriff_elected,
        "current_speaker": state.current_speaker,
        "speech_order": state.speech_order,
        "pk_candidates": state.pk_candidates,
        "eliminated_today": state.eliminated_today,
        "players": players,
        "public_log": state.public_log[-50:],  # 最近 50 条
        "alive_count": len(state.get_alive_players()),
    }

    # 上帝/玩家视角附加私密日志
    if perspective == "god":
        result["private_logs"] = {
            str(pid): logs[-20:]
            for pid, logs in state.private_logs.items()
        }
    elif player_id is not None and player_id in state.private_logs:
        result["private_log"] = state.private_logs[player_id][-20:]

    return result
