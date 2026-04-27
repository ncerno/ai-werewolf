"""规则引擎：纯函数，无副作用，可独立测试。"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .state import GameState

from .state import Faction, Phase, Player, Role


# ============================================================
# 胜利条件判定
# ============================================================

def check_winner(state: GameState) -> Optional[Faction]:
    """判定胜负。返回获胜阵营，否则 None。"""
    alive_wolves = state.get_alive_wolves()
    alive_good = state.get_alive_by_faction(Faction.GOOD)

    # 所有狼人出局 → 好人胜
    if len(alive_wolves) == 0:
        return Faction.GOOD

    # 狼数 >= 存活好人数 → 狼人胜
    if len(alive_wolves) >= len(alive_good):
        return Faction.WOLF

    alive_seers = state.get_alive_by_role(Role.SEER)
    alive_witches = state.get_alive_by_role(Role.WITCH)
    alive_hunters = state.get_alive_by_role(Role.HUNTER)
    alive_fools = state.get_alive_by_role(Role.FOOL)
    alive_gods = alive_seers + alive_witches + alive_hunters + alive_fools

    alive_villagers = state.get_alive_by_role(Role.VILLAGER)

    # 屠边：所有神出局 OR 所有平民出局
    if len(alive_gods) == 0 or len(alive_villagers) == 0:
        return Faction.WOLF

    return None


# ============================================================
# 行动合法性验证
# ============================================================

def validate_action(state: GameState, player_id: int, action: str, target_id: int = 0) -> tuple[bool, str]:
    """验证行动是否合法。返回 (合法, 错误信息)。"""
    player = state.get_player(player_id)
    if not player:
        return False, f"玩家 {player_id} 不存在"

    if not player.alive:
        return False, f"玩家 {player_id} 已死亡"

    action_upper = action.upper().strip()

    validators = {
        "KILL": _validate_kill,
        "CHECK": _validate_check,
        "VOTE": _validate_vote,
        "SHOOT": _validate_shoot,
        "SKIP": _validate_skip,
        "SAVE": _validate_save,
        "POISON": _validate_poison,
        "GIVE_BADGE": _validate_give_badge,
    }

    validator = validators.get(action_upper)
    if not validator:
        return False, f"未知行动: {action}"

    return validator(state, player, target_id)


def _validate_kill(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if player.role != Role.WEREWOLF:
        return False, "只有狼人可以击杀"
    if target_id == 0:
        return False, "击杀需要指定目标"
    target = state.get_player(target_id)
    if not target:
        return False, f"目标 {target_id} 不存在"
    if not target.alive:
        return False, f"目标 {target_id} 已死亡"
    if target.role == Role.WEREWOLF and target_id != player.player_id:
        return False, "不能击杀狼同伴（自刀除外）"
    return True, ""


def _validate_check(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if player.role != Role.SEER:
        return False, "只有预言家可以查验"
    if target_id == 0:
        return False, "查验需要指定目标"
    target = state.get_player(target_id)
    if not target:
        return False, f"目标 {target_id} 不存在"
    if not target.alive:
        return False, f"目标 {target_id} 已死亡"
    return True, ""


def _validate_vote(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if not player.has_vote:
        return False, "没有投票权"
    if target_id == 0:
        return False, "投票需要指定目标"
    target = state.get_player(target_id)
    if not target:
        return False, f"目标 {target_id} 不存在"
    if not target.alive:
        return False, f"目标 {target_id} 已死亡"
    # PK 阶段只能投 PK 台上的玩家
    if state.phase == Phase.DAY_PK_VOTE and state.pk_candidates:
        if target_id not in state.pk_candidates:
            return False, f"PK 阶段只能投 PK 台上的玩家: {state.pk_candidates}"
    return True, ""


def _validate_shoot(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if player.role != Role.HUNTER:
        return False, "只有猎人可以开枪"
    if not player.hunter_can_shoot:
        return False, "猎人当前不能开枪"
    if not target_id:
        return False, "开枪需要指定目标"
    target = state.get_player(target_id)
    if not target:
        return False, f"目标 {target_id} 不存在"
    if not target.alive:
        return False, f"目标 {target_id} 已死亡"
    return True, ""


def _validate_skip(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    return True, ""


def _validate_save(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if player.role != Role.WITCH:
        return False, "只有女巫可以使用解药"
    if not player.witch_save_available:
        return False, "解药已经使用过"
    return True, ""


def _validate_poison(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if player.role != Role.WITCH:
        return False, "只有女巫可以使用毒药"
    if not player.witch_poison_available:
        return False, "毒药已经使用过"
    if target_id == 0:
        return False, "毒药需要指定目标"
    target = state.get_player(target_id)
    if not target:
        return False, f"目标 {target_id} 不存在"
    if not target.alive:
        return False, f"目标 {target_id} 已死亡"
    return True, ""


def _validate_give_badge(state: GameState, player: Player, target_id: int) -> tuple[bool, str]:
    if player.player_id != state.sheriff_id:
        return False, "只有警长可以移交警徽"
    if target_id == 0:
        return False, "移交警徽需要指定目标"
    target = state.get_player(target_id)
    if not target:
        return False, f"目标 {target_id} 不存在"
    if not target.alive:
        return False, f"目标 {target_id} 已死亡"
    return True, ""


# ============================================================
# 计票
# ============================================================

def tally_votes(votes: dict[int, int], sheriff_id: int = None, sheriff_voted_id: int = None) -> dict:
    """计票并返回结果。

    Args:
        votes: {voter_id: target_id}
        sheriff_id: 警长 ID（如有）
        sheriff_voted_id: 警长投的目标（如警长参与投票）

    Returns:
        {
            "counts": {target_id: float_vote_count},
            "top": [最多票玩家列表],
            "max_votes": 最高票数,
            "is_tie": True/False,
            "tied_players": [平票玩家列表]  # 仅当 is_tie=True
        }
    """
    counts: dict[int, float] = {}

    for voter_id, target_id in votes.items():
        weight = 1.0
        if voter_id == sheriff_id:
            weight = 1.5
        counts[target_id] = counts.get(target_id, 0) + weight

    if not counts:
        return {"counts": {}, "top": [], "max_votes": 0, "is_tie": False, "tied_players": []}

    max_votes = max(counts.values())
    top = [pid for pid, cnt in counts.items() if cnt == max_votes]

    return {
        "counts": counts,
        "top": top,
        "max_votes": max_votes,
        "is_tie": len(top) > 1,
        "tied_players": top if len(top) > 1 else [],
    }


# ============================================================
# 游戏流程辅助
# ============================================================

def get_night_order(state: GameState) -> list[Phase]:
    """返回当前夜晚的唤醒顺序。"""
    order = [
        Phase.NIGHT_WOLF,
        Phase.NIGHT_WITCH,
        Phase.NIGHT_SEER,
        Phase.NIGHT_HUNTER,
    ]
    # 白痴仅首夜睁眼
    if state.turn == 1:
        order.append(Phase.NIGHT_FOOL)
    return order


def get_default_speech_direction(state: GameState) -> str:
    if state.sheriff_id:
        # 警长决定方向，默认警左
        return "left"
    return "left"  # 无警长时上帝决定，默认左


# ============================================================
# 狼人投票聚合：多数决
# ============================================================

def resolve_wolf_votes(wolf_votes: dict[int, int]) -> Optional[int]:
    """狼人独立投票后聚合：多数决。平票则随机选。支持 SKIP。

    Args:
        wolf_votes: {wolf_id: target_id_or_0_for_skip}

    Returns:
        击杀目标 ID，或 None 表示空刀
    """
    skip_count = sum(1 for v in wolf_votes.values() if v == 0)
    real_votes = {k: v for k, v in wolf_votes.items() if v != 0}

    if not real_votes:
        return None  # 全部 SKIP → 空刀

    # 计数
    counts: dict[int, int] = {}
    for target_id in real_votes.values():
        counts[target_id] = counts.get(target_id, 0) + 1

    max_count = max(counts.values())
    top_targets = [tid for tid, cnt in counts.items() if cnt == max_count]

    if len(top_targets) == 1:
        return top_targets[0]
    else:
        return random.choice(top_targets)


# ============================================================
# 警长竞选投票
# ============================================================

def resolve_election(votes: dict[int, int], candidates: list[int]) -> Optional[int]:
    """警长竞选计票。返回当选者或 None（无警长）。

    Args:
        votes: {voter_id: candidate_id}，退水玩家无投票权
        candidates: 仍在竞选中的玩家 ID 列表
    """
    counts: dict[int, int] = {}

    for voter_id, target_id in votes.items():
        if target_id in candidates:
            counts[target_id] = counts.get(target_id, 0) + 1

    if not counts:
        return None

    max_count = max(counts.values())
    top = [cid for cid, cnt in counts.items() if cnt == max_count]

    if len(top) == 1:
        return top[0]
    return None  # 平票，无警长
