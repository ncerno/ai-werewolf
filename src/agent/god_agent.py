"""GodAgent：模式三（人类玩家）的 AI 上帝/主持人。

负责用自然语言叙述游戏事件、引导人类玩家输入行动。
"""
from __future__ import annotations

from openai import AsyncOpenAI


class GodAgent:
    """AI 上帝，主持游戏。仅用于玩家模式。"""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._config = cfg

        api_key = cfg.get("api_key", "")
        base_url = cfg.get("api_base", "")
        self._client = AsyncOpenAI(
            api_key=api_key if api_key else "sk-placeholder",
            base_url=base_url if base_url else None,
            timeout=60.0,
        )

        self._system_prompt = (
            "你是一个狼人杀游戏的上帝（主持人）。"
            "你的任务是用生动自然的语言叙述游戏事件，引导人类玩家参与。"
            "你需要保持中立，不偏袒任何一方。"
            "描述要简洁清晰，适合在聊天界面中阅读。"
            "不要暴露任何隐藏信息（如玩家身份、夜晚行动细节），除非游戏规则要求公开。"
        )

    async def narrate_event(self, event_type: str, context: dict) -> str:
        """叙述游戏事件。

        Args:
            event_type: 事件类型（night_start/day_announce/election/speech_turn/vote_result/game_over）
            context: 事件上下文数据
        """
        prompts = {
            "night_start": f"夜晚降临，第 {context.get('turn', '?')} 夜。所有人闭眼。",
            "day_announce": self._narrate_deaths(context),
            "election": self._narrate_election(context),
            "speech_turn": f"请 {context.get('player_id', '?')} 号玩家发言。",
            "vote_result": self._narrate_vote_result(context),
            "game_over": self._narrate_game_over(context),
        }
        base = prompts.get(event_type, "")
        if not base:
            return ""

        # 用 LLM 润色
        try:
            response = await self._client.chat.completions.create(
                model=self._config.get("model", "deepseek-chat"),
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": f"请将以下游戏事件用自然语言描述出来（保持简洁，不超过100字）：\n{base}"},
                ],
                temperature=self._config.get("temperature", 0.3),
                max_tokens=self._config.get("max_tokens", 4096),
            )
            return response.choices[0].message.content or base
        except Exception:
            return base

    async def prompt_human_action(self, prompt_type: str, context: dict) -> str:
        """生成引导人类玩家行动的提示文本。"""
        prompts = {
            "night_action": (
                f"夜晚阶段。你的身份是 {context.get('role', '?')}。"
                f"请选择你的行动。"
            ),
            "vote": "白天投票阶段。请选择你要放逐的玩家编号。",
            "speech": "轮到你发言了。请输入你的发言内容。",
            "election": "警长竞选。请选择你要投票的候选人编号。",
            "sheriff_speech": "你是警长候选人。请发表你的竞选发言。",
        }
        return prompts.get(prompt_type, "请做出你的选择。")

    async def describe_game_start(self, human_role: str, player_id: int) -> str:
        """开场介绍。"""
        role_names = {
            "werewolf": "狼人",
            "seer": "预言家",
            "witch": "女巫",
            "hunter": "猎人",
            "fool": "白痴",
            "villager": "平民",
        }
        role_name = role_names.get(human_role, human_role)

        prompt = (
            f"游戏开始！你是 {player_id} 号玩家，你的身份是 {role_name}。\n"
            f"请用一段简短的文字欢迎人类玩家，告知其身份，并说明游戏即将开始。"
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._config.get("model", "deepseek-chat"),
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._config.get("temperature", 0.3),
                max_tokens=self._config.get("max_tokens", 4096),
            )
            return response.choices[0].message.content or prompt
        except Exception:
            return f"游戏开始！你是 {player_id} 号玩家，你的身份是 **{role_name}**。祝你好运！"

    # ============================================================
    # 内部叙述模板
    # ============================================================

    def _narrate_deaths(self, context: dict) -> str:
        deaths = context.get("deaths", [])
        if not deaths:
            return "天亮了。昨夜是平安夜，没有人死亡。"
        death_str = "、".join(f"{d}号" for d in deaths)
        return f"天亮了。昨夜死亡玩家：{death_str}。请等待上帝公布死讯。"

    def _narrate_election(self, context: dict) -> str:
        sheriff_id = context.get("sheriff_id")
        if sheriff_id:
            return f"警长竞选结束。{sheriff_id} 号玩家当选警长！"
        return "警长竞选结束。由于平票，本局没有警长。"

    def _narrate_vote_result(self, context: dict) -> str:
        eliminated = context.get("eliminated")
        reason = context.get("reason", "")
        if eliminated:
            return f"投票放逐结果：{eliminated} 号玩家被放逐出局。"
        if reason == "平票":
            return "投票结果：平票。经过PK后仍然平票，无人被放逐。"
        return "投票结束。"

    def _narrate_game_over(self, context: dict) -> str:
        winner = context.get("winner", "")
        if winner == "good":
            return "游戏结束！好人阵营获胜，所有狼人已被消灭。"
        elif winner == "wolf":
            return "游戏结束！狼人阵营获胜。"
        return "游戏结束。"
