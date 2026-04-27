"""行动解析器：从 LLM 回复中提取行动指令和发言内容。

纯函数模块，无 LLM 调用，无状态。可直接单元测试。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

# ============================================================
# 正则模式
# ============================================================

_ACTION_RE = re.compile(r'【行动】\s*(\S+)\s*(\d*)', re.IGNORECASE)
_SPEECH_RE = re.compile(r'【发言】\s*([\s\S]*?)(?=【行动】|【发言】|$)', re.IGNORECASE)

_VALID_ACTIONS = {"KILL", "CHECK", "VOTE", "SHOOT", "SKIP", "SAVE", "POISON", "GIVE_BADGE"}

_RETRY_MESSAGE = (
    "你的回复格式不正确。请严格按照以下格式回复：\n"
    "【行动】ACTION TARGET_ID\n"
    "例如：【行动】VOTE 3\n"
    "如果你不需要行动，请回复：【行动】SKIP"
)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ActionResult:
    """LLM 决策结果。"""
    action: str = ""          # KILL/CHECK/VOTE/SHOOT/SKIP/SAVE/POISON/GIVE_BADGE
    target_id: int = 0        # 目标玩家 ID（无目标行动为 0）
    speech: str = ""          # 发言内容（如有）
    raw_response: str = ""    # LLM 原始回复（日志用）


# ============================================================
# 公共 API
# ============================================================

def parse_action(response: str) -> tuple[str, int]:
    """从 LLM 回复中提取 (ACTION, TARGET_ID)。未找到返回 ("", 0)。"""
    m = _ACTION_RE.search(response)
    if not m:
        return ("", 0)
    action = m.group(1).upper().strip()
    target_str = m.group(2).strip()
    target_id = int(target_str) if target_str else 0
    return (action, target_id)


def parse_speech(response: str) -> str:
    """从 LLM 回复中提取发言内容。未找到返回全文。"""
    m = _SPEECH_RE.search(response)
    if not m:
        return response.strip()
    return m.group(1).strip()


def parse(response: str) -> ActionResult:
    """完整解析 LLM 回复，提取行动、目标、发言。"""
    action, target = parse_action(response)
    speech = parse_speech(response)
    return ActionResult(
        action=action,
        target_id=target,
        speech=speech,
        raw_response=response,
    )


def get_retry_message() -> str:
    """获取格式错误的提示消息。"""
    return _RETRY_MESSAGE


def random_action(
    action_hint: str,
    alive_ids: list[int],
    self_id: int,
    valid_targets: list[int] | None = None,
) -> ActionResult:
    """当 LLM 两次均格式错误时，生成随机合法行动作为兜底。

    Args:
        action_hint: 行动提示（KILL/CHECK/VOTE/VOTE_ELECTION/SHOOT/WITCH_ACTION/GIVE_BADGE）
        alive_ids: 存活玩家 ID 列表
        self_id: 自己的 player_id
        valid_targets: 合法目标列表（如 PK 候选人），None 表示所有存活非己玩家
    """
    candidates = valid_targets or [pid for pid in alive_ids if pid != self_id]

    action_map: dict[str, tuple[str, object]] = {
        "KILL": ("KILL", lambda: random.choice(candidates) if candidates else 0),
        "CHECK": ("CHECK", lambda: random.choice(candidates) if candidates else 0),
        "VOTE": ("VOTE", lambda: random.choice(candidates) if candidates else 0),
        "VOTE_ELECTION": ("VOTE", lambda: random.choice(candidates) if candidates else 0),
        "SHOOT": ("SKIP", lambda: 0),
        "WITCH_ACTION": ("SKIP", lambda: 0),
        "GIVE_BADGE": ("GIVE_BADGE", lambda: random.choice(candidates) if candidates else 0),
    }

    if action_hint not in action_map:
        return ActionResult(action="SKIP", target_id=0, speech="", raw_response="[FALLBACK]")

    action_name, target_fn = action_map[action_hint]
    target = target_fn() if callable(target_fn) else target_fn
    return ActionResult(
        action=action_name,
        target_id=target if isinstance(target, int) else 0,
        speech="",
        raw_response="[FALLBACK]",
    )
