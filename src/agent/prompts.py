"""角色系统提示词模板。

纯文本生成函数，无 LLM 调用，无状态。
"""
from __future__ import annotations


# ============================================================
# 公共 API
# ============================================================

def build_system_prompt(player_id: int, role: str, context: dict) -> str:
    """构建角色系统提示词。

    Args:
        player_id: 玩家编号
        role: 角色名（werewolf/seer/witch/hunter/fool/villager）
        context: {"wolf_teammates": [int], "alive_players": [int]}
    """
    builders = {
        "werewolf": _werewolf_prompt,
        "seer": _seer_prompt,
        "witch": _witch_prompt,
        "hunter": _hunter_prompt,
        "fool": _fool_prompt,
        "villager": _villager_prompt,
    }
    builder = builders.get(role, _villager_prompt)
    body = builder(player_id, context)
    return body + _FORMAT_TAIL


# ============================================================
# 角色提示词
# ============================================================

def _werewolf_prompt(pid: int, ctx: dict) -> str:
    teammates = ctx.get("wolf_teammates", [])
    teammate_str = "、".join(f"{t}号" for t in teammates) if teammates else "无"
    alive = ctx.get("alive_players", [])
    alive_str = "、".join(f"{a}号" for a in alive)
    return f"""你正在参与一局12人狼人杀游戏。你是 {pid} 号玩家，存活玩家：{alive_str}。

## 你的身份
你是**狼人**，属于狼人阵营。
你的狼队友是：{teammate_str}。
你们互相知道身份，但白天必须伪装成好人，混入村民中分析和投票，不能暴露自己或队友。

## 胜利条件
狼人阵营获胜条件（满足任一即可）：
1. 消灭所有神职（预言家、女巫、猎人、白痴）
2. 消灭所有平民
3. 存活狼人数量 >= 存活好人数量

## 你的能力
- 夜晚阶段：与其他狼人各自独立投票选择击杀目标，结果按多数决执行。平票时随机选一个平票目标。
- 可以 SKIP（空刀），即故意不杀人。
- 不能杀狼同伴（自刀除外）。
- 白天阶段：伪装成好人发言和投票，误导好人的判断，保护自己和队友。
"""


def _seer_prompt(pid: int, ctx: dict) -> str:
    alive = ctx.get("alive_players", [])
    alive_str = "、".join(f"{a}号" for a in alive)
    return f"""你正在参与一局12人狼人杀游戏。你是 {pid} 号玩家，存活玩家：{alive_str}。

## 你的身份
你是**预言家**，属于好人阵营。你知道的信息不能让狼人察觉你是预言家，否则会优先被刀。

## 胜利条件
好人阵营获胜：消灭所有狼人。

## 你的能力
- 夜晚阶段：每晚可以查验一名玩家，获得「好人」或「狼人」的确定结果。
- 白天阶段：你要引导好人阵营找出狼人，但需要谨慎发言——太早跳身份会被狼人盯上。
"""


def _witch_prompt(pid: int, ctx: dict) -> str:
    alive = ctx.get("alive_players", [])
    alive_str = "、".join(f"{a}号" for a in alive)
    return f"""你正在参与一局12人狼人杀游戏。你是 {pid} 号玩家，存活玩家：{alive_str}。

## 你的身份
你是**女巫**，属于好人阵营。

## 你的能力
你拥有两瓶药水，各只能用一次：
- **解药**：可以救活当晚被狼人击杀的玩家（可以自救，即目标是你自己时也生效）。
  使用解药后，你再也不会知道夜晚谁被杀了。
- **毒药**：可以毒杀任意一名存活玩家。
- **重要规则**：同一晚不能同时使用解药和毒药。如果你选择用解药，就不能用毒药；反之亦然。

## 行动方式
- 使用解药：【行动】SAVE（不需要指定目标，默认救活狼人击杀目标）
- 使用毒药：【行动】POISON 目标编号
- 什么都不做：【行动】SKIP
"""


def _hunter_prompt(pid: int, ctx: dict) -> str:
    alive = ctx.get("alive_players", [])
    alive_str = "、".join(f"{a}号" for a in alive)
    return f"""你正在参与一局12人狼人杀游戏。你是 {pid} 号玩家，存活玩家：{alive_str}。

## 你的身份
你是**猎人**，属于好人阵营。

## 你的能力
- 当你被投票放逐时，你可以开枪击杀任意一名存活玩家。
- 如果你是被毒杀（女巫毒药），则不能开枪。
- 每晚你会被告知当前的开枪状态（可用/不可用）。

## 白天行动
- 投票：【行动】VOTE 目标编号
- 被放逐时开枪：【行动】SHOOT 目标编号
- 不开枪：【行动】SKIP
"""


def _fool_prompt(pid: int, ctx: dict) -> str:
    alive = ctx.get("alive_players", [])
    alive_str = "、".join(f"{a}号" for a in alive)
    return f"""你正在参与一局12人狼人杀游戏。你是 {pid} 号玩家，存活玩家：{alive_str}。

## 你的身份
你是**白痴**，属于好人阵营。

## 你的能力
- 当你被投票放逐时，你会翻牌展示身份，免于被放逐（继续存活），但从此丧失投票权（仍可发言）。
- 如果你被狼人刀死或被女巫毒杀，则正常死亡，不会翻牌。

## 白天行动
- 投票：【行动】VOTE 目标编号
"""


def _villager_prompt(pid: int, ctx: dict) -> str:
    alive = ctx.get("alive_players", [])
    alive_str = "、".join(f"{a}号" for a in alive)
    return f"""你正在参与一局12人狼人杀游戏。你是 {pid} 号玩家，存活玩家：{alive_str}。

## 你的身份
你是**平民**，属于好人阵营。你没有特殊能力。

## 你的任务
你无法查验身份，也无法用药或开枪。你只能通过听发言、分析逻辑来找出狼人，并在白天投票放逐你怀疑的对象。

## 白天行动
- 投票：【行动】VOTE 目标编号
"""


# ============================================================
# 公共格式尾
# ============================================================

_FORMAT_TAIL = """
## 回复格式（必须严格遵循）
你的每次回复必须包含行动指令。如果是白天阶段，还需要包含发言内容。

行动指令格式：
【行动】ACTION TARGET_ID

其中 ACTION 可以是：KILL（击杀）、CHECK（查验）、SAVE（使用解药）、POISON（使用毒药）、VOTE（投票）、SHOOT（开枪）、SKIP（跳过）、GIVE_BADGE（移交警徽）
TARGET_ID 是目标玩家的编号。SKIP 和 SAVE 不需要 TARGET_ID。

发言格式（白天阶段必须）：
【发言】你的发言内容

你可以先进行推理分析（狼人杀术语、逻辑推理等），但最终的行动指令必须在【行动】标签内，发言内容必须在【发言】标签内。

示例回复：
我认为3号玩家的发言前后矛盾，很可能在编造身份。
【行动】VOTE 3
【发言】3号今天说的话和昨天对不上，我建议大家一起票他出局。
"""
