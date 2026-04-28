"""PlayerAgent：单个 AI 玩家的 LLM Agent。

负责管理该玩家的 memory、调用 LLM 做决策、解析结果。
Controller 通过 PlayerAgent 与 LLM 交互，不直接调用 openai。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from .parser import ActionResult, parse, get_retry_message, random_action
from .prompts import build_system_prompt

if TYPE_CHECKING:
    from ..engine.state import GameState


class PlayerAgent:
    """单个 AI 玩家。持有角色、记忆、LLM 客户端。"""

    def __init__(
        self,
        player_id: int,
        role: str,
        model_config: dict,
        game_state: GameState,
    ):
        self.player_id = player_id
        self.role = role
        self._config = model_config
        self._state = game_state
        self.turn_count = 0

        api_key = model_config.get("api_key", "")
        base_url = model_config.get("api_base", "")
        self._client = AsyncOpenAI(
            api_key=api_key if api_key else "sk-placeholder",
            base_url=base_url if base_url else None,
            timeout=60.0,
        )

        system_prompt = self._build_system_prompt()
        self.memory: list[dict] = [
            {"role": "system", "content": system_prompt}
        ]

    # ============================================================
    # 公开方法
    # ============================================================

    def observe(self, event: str) -> None:
        """追加事件到 memory。"""
        self.memory.append({"role": "user", "content": event})

    async def decide(self, action_hint: str, context: dict) -> ActionResult:
        """请求 LLM 做出行动决策。含格式校验重试和兜底。"""
        self.turn_count += 1

        prompt = self._build_decision_prompt(action_hint, context)
        messages = self.memory + [{"role": "user", "content": prompt}]

        # 第一次尝试
        response = await self._call_llm(messages)
        result = parse(response)

        if result.action:
            self._record_decision(result)
            return result

        # 格式错误 → 重试一次
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": get_retry_message()})

        response2 = await self._call_llm(messages)
        result2 = parse(response2)

        if result2.action:
            self._record_decision(result2)
            return result2

        # 仍然失败 → 随机兜底
        alive_ids = self._state.get_alive_ids()
        result3 = random_action(action_hint, alive_ids, self.player_id)
        self._record_decision(result3)
        return result3

    async def speak(self, context: dict) -> str:
        """生成白天发言。"""
        prompt = self._build_speech_prompt(context)
        messages = self.memory + [{"role": "user", "content": prompt}]

        response = await self._call_llm(messages)
        speech = response.strip()

        # 如果有【发言】标签，提取内容；否则用全文
        from .parser import parse_speech
        extracted = parse_speech(response)
        if extracted:
            speech = extracted

        self.observe(f"[你的发言] {speech}")
        return speech

    async def summarize(self) -> None:
        """每 2 回合压缩旧 memory。"""
        if self.turn_count % 2 != 0:
            return

        # 保留 system prompt(index 0) + 最近 10 条
        if len(self.memory) <= 11:
            return

        old_messages = self.memory[1:-10]
        recent = self.memory[-10:]

        summary_prompt = (
            "请用一段话总结以下游戏历史中的关键信息（身份猜测、投票倾向、可疑行为、夜间结果等）。"
            "只输出总结内容，不要输出其他格式。\n\n"
        )
        summary_prompt += "\n".join(
            f"[{m['role']}] {m['content'][:500]}" for m in old_messages
        )

        try:
            summary_response = await self._call_llm([
                {"role": "user", "content": summary_prompt}
            ])
            summary = summary_response.strip()
        except Exception:
            import traceback
            traceback.print_exc()
            summary = f"（历史记录过长，已省略 {len(old_messages)} 条消息）"

        self.memory = [
            self.memory[0],
            {"role": "system", "content": f"【历史摘要】{summary}"},
        ] + recent

    # ============================================================
    # 内部方法
    # ============================================================

    def _build_system_prompt(self) -> str:
        """构建角色系统提示词。"""
        context = {
            "alive_players": self._state.get_alive_ids(),
        }
        if self.role == "werewolf":
            wolves = self._state.get_alive_wolves()
            context["wolf_teammates"] = [
                w.player_id for w in wolves if w.player_id != self.player_id
            ]
        return build_system_prompt(self.player_id, self.role, context)

    def _build_decision_prompt(self, action_hint: str, context: dict) -> str:
        """构建请求行动决策的 prompt。"""
        phase_descriptions = {
            "KILL": "狼人睁眼，请选择今晚的击杀目标。你可以跟狼队友投票同一个目标，也可以投不同目标（最终多数决）。输入【行动】KILL 目标编号 或 【行动】SKIP",
            "CHECK": "预言家睁眼，请选择要查验的玩家。输入【行动】CHECK 目标编号",
            "WITCH_ACTION": self._build_witch_prompt(context),
            "VOTE": "请投票选择你要放逐的玩家。输入【行动】VOTE 目标编号",
            "VOTE_ELECTION": "请投票选择你支持的警长候选人。输入【行动】VOTE 目标编号",
            "SHOOT": "你被投票放逐了！猎人可以开枪带走一名玩家，也可以选择不开枪。输入【行动】SHOOT 目标编号 或 【行动】SKIP",
            "GIVE_BADGE": "你是警长，即将被放逐。请选择将警徽移交给谁。输入【行动】GIVE_BADGE 目标编号",
        }
        desc = phase_descriptions.get(action_hint, f"请做出 {action_hint} 行动")
        return f"{desc}\n\n请输出你的行动指令。"

    def _build_witch_prompt(self, context: dict) -> str:
        dead_id = context.get("dead_player")
        save_ok = context.get("save_available", False)
        poison_ok = context.get("poison_available", False)

        if dead_id:
            dead_info = f"今晚 {dead_id} 号玩家被狼人击杀。"
        else:
            dead_info = "今晚是平安夜（没有人被狼人击杀）。"

        options = []
        if save_ok and dead_id:
            options.append("【行动】SAVE 使用解药救活该玩家")
        if poison_ok:
            options.append("【行动】POISON 目标编号 使用毒药毒杀一名玩家")
        options.append("【行动】SKIP 什么都不做")

        return (
            f"女巫睁眼。{dead_info}\n"
            f"解药：{'可用' if save_ok else '已用'} | 毒药：{'可用' if poison_ok else '已用'}\n"
            f"注意：同一晚不能同时使用解药和毒药。\n"
            f"可选行动：\n" + "\n".join(f"  - {o}" for o in options)
        )

    def _build_speech_prompt(self, context: dict) -> str:
        """构建发言 prompt。"""
        phase = context.get("phase", "DAY_SPEECH")
        return (
            f"现在是白天发言阶段。请根据你已知的信息进行发言，发表你对局势的分析和判断。\n"
            f"请先发言，然后用【行动】VOTE 目标编号 表达你当前的投票倾向（仅供参考，正式投票会另做）。\n"
            f"请输出你的发言。"
        )

    async def _call_llm(self, messages: list[dict]) -> str:
        """调用 LLM，返回文本内容。"""
        model = self._config.get("model", "deepseek-chat")
        temperature = self._config.get("temperature", 0.7)
        max_tokens = self._config.get("max_tokens", 2048)

        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def _record_decision(self, result: ActionResult) -> None:
        """将决策结果记录到 memory。"""
        if result.action == "SKIP":
            self.observe(f"[你的行动] {result.action}")
        elif result.target_id:
            self.observe(f"[你的行动] {result.action} → {result.target_id}号")
        else:
            self.observe(f"[你的行动] {result.action}")