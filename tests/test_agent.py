"""LLM Agent 层单元测试。"""
import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.agent.parser import (
    ActionResult,
    parse_action,
    parse_speech,
    parse,
    random_action,
    get_retry_message,
)
from src.agent.prompts import build_system_prompt
from src.engine.state import GameState, Player, Role


def make_state(roles: list[Role]) -> GameState:
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
    return GameState(players=players)


# ============================================================
# TestActionParser
# ============================================================

class TestActionParser:
    def test_extract_kill_with_target(self):
        action, target = parse_action("【行动】KILL 3")
        assert action == "KILL"
        assert target == 3

    def test_extract_skip_without_target(self):
        action, target = parse_action("【行动】SKIP")
        assert action == "SKIP"
        assert target == 0

    def test_extract_save_without_target(self):
        action, target = parse_action("【行动】SAVE")
        assert action == "SAVE"
        assert target == 0

    def test_extract_check(self):
        action, target = parse_action("【行动】CHECK 5")
        assert action == "CHECK"
        assert target == 5

    def test_extract_vote(self):
        action, target = parse_action("【行动】VOTE 7")
        assert action == "VOTE"
        assert target == 7

    def test_extract_poison(self):
        action, target = parse_action("【行动】POISON 12")
        assert action == "POISON"
        assert target == 12

    def test_extract_give_badge(self):
        action, target = parse_action("【行动】GIVE_BADGE 4")
        assert action == "GIVE_BADGE"
        assert target == 4

    def test_case_insensitive_action(self):
        action, target = parse_action("【行动】kill 3")
        assert action == "KILL"
        assert target == 3

    def test_extra_whitespace_tolerant(self):
        action, target = parse_action("【行动】  KILL  3  ")
        assert action == "KILL"
        assert target == 3

    def test_no_tags_returns_empty(self):
        action, target = parse_action("我认为3号是狼，没有标签")
        assert action == ""
        assert target == 0

    def test_invalid_action_still_extracted(self):
        # parser 只提取，不校验合法性（由 rules 模块校验）
        action, target = parse_action("【行动】INVALID 1")
        assert action == "INVALID"
        assert target == 1

    def test_extract_speech(self):
        speech = parse_speech("【发言】我认为3号是狼")
        assert speech == "我认为3号是狼"

    def test_extract_both_action_and_speech(self):
        result = parse("推理分析...【行动】VOTE 7【发言】我认为7号很可疑")
        assert result.action == "VOTE"
        assert result.target_id == 7
        assert result.speech == "我认为7号很可疑"

    def test_speech_only_no_action(self):
        result = parse("【发言】今天天气真好")
        assert result.action == ""
        assert result.target_id == 0
        assert result.speech == "今天天气真好"

    def test_speech_before_action(self):
        result = parse("【发言】7号是狼【行动】VOTE 7")
        assert result.action == "VOTE"
        assert result.target_id == 7
        assert result.speech == "7号是狼"

    def test_no_tags_full_text_as_speech(self):
        result = parse("自由文本无标签")
        assert result.action == ""
        assert result.target_id == 0
        assert result.speech == "自由文本无标签"

    def test_multiline_speech(self):
        result = parse("【发言】第一行\n第二行\n第三行【行动】VOTE 2")
        assert result.action == "VOTE"
        assert "第一行" in result.speech

    def test_parse_preserves_raw_response(self):
        raw = "推理...【行动】KILL 3"
        result = parse(raw)
        assert result.raw_response == raw


# ============================================================
# TestPrompts
# ============================================================

class TestPrompts:
    def test_werewolf_prompt_contains_teammates(self):
        ctx = {"wolf_teammates": [2, 3, 4], "alive_players": list(range(1, 13))}
        prompt = build_system_prompt(1, "werewolf", ctx)
        assert "狼人" in prompt
        assert "2号" in prompt
        assert "3号" in prompt
        assert "4号" in prompt
        assert "【行动】" in prompt
        assert "【发言】" in prompt

    def test_seer_prompt_contains_check(self):
        ctx = {"alive_players": list(range(1, 13))}
        prompt = build_system_prompt(3, "seer", ctx)
        assert "预言家" in prompt
        assert "查验" in prompt
        assert "【行动】" in prompt

    def test_witch_prompt_contains_save_poison(self):
        ctx = {"alive_players": list(range(1, 13))}
        prompt = build_system_prompt(5, "witch", ctx)
        assert "女巫" in prompt
        assert "解药" in prompt
        assert "毒药" in prompt

    def test_hunter_prompt_contains_shoot(self):
        ctx = {"alive_players": list(range(1, 13))}
        prompt = build_system_prompt(7, "hunter", ctx)
        assert "猎人" in prompt
        assert "开枪" in prompt or "SHOOT" in prompt

    def test_fool_prompt_contains_reveal(self):
        ctx = {"alive_players": list(range(1, 13))}
        prompt = build_system_prompt(8, "fool", ctx)
        assert "白痴" in prompt
        assert "翻牌" in prompt or "免死" in prompt

    def test_villager_prompt_has_no_ability(self):
        ctx = {"alive_players": list(range(1, 13))}
        prompt = build_system_prompt(10, "villager", ctx)
        assert "平民" in prompt
        assert "没有特殊能力" in prompt or "无特殊能力" in prompt

    def test_all_prompts_contain_format_tags(self):
        ctx = {"alive_players": list(range(1, 13)), "wolf_teammates": [2, 3, 4]}
        for role in ["werewolf", "seer", "witch", "hunter", "fool", "villager"]:
            prompt = build_system_prompt(1, role, ctx)
            assert "【行动】" in prompt, f"{role} prompt missing 【行动】"
            assert "【发言】" in prompt, f"{role} prompt missing 【发言】"

    def test_prompt_contains_player_id(self):
        ctx = {"alive_players": list(range(1, 13))}
        prompt = build_system_prompt(9, "villager", ctx)
        assert "9 号" in prompt or "9号" in prompt


# ============================================================
# TestRandomAction
# ============================================================

class TestRandomAction:
    def test_random_kill_returns_valid_target(self):
        result = random_action("KILL", [1, 2, 3, 4], 1)
        assert result.action == "KILL"
        assert result.target_id in [2, 3, 4]

    def test_random_vote_returns_valid_target(self):
        result = random_action("VOTE", [1, 2, 3], 2)
        assert result.action == "VOTE"
        assert result.target_id in [1, 3]

    def test_random_witch_returns_skip(self):
        result = random_action("WITCH_ACTION", [1, 2, 3], 1)
        assert result.action == "SKIP"
        assert result.target_id == 0

    def test_random_shoot_returns_skip(self):
        result = random_action("SHOOT", [1, 2, 3], 1)
        assert result.action == "SKIP"
        assert result.target_id == 0

    def test_random_with_valid_targets(self):
        result = random_action("VOTE", [1, 2, 3, 4], 1, valid_targets=[2, 3])
        assert result.action == "VOTE"
        assert result.target_id in [2, 3]

    def test_unknown_hint_returns_skip(self):
        result = random_action("UNKNOWN", [1, 2, 3], 1)
        assert result.action == "SKIP"

    def test_give_badge_returns_valid_target(self):
        result = random_action("GIVE_BADGE", [1, 2, 3], 1)
        assert result.action == "GIVE_BADGE"
        assert result.target_id in [2, 3]


# ============================================================
# TestPlayerAgent (需要 mock LLM)
# ============================================================

class TestPlayerAgentMemory:
    def test_observe_appends_to_memory(self):
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent
        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)
        initial_len = len(agent.memory)
        agent.observe("测试事件")
        assert len(agent.memory) == initial_len + 1
        assert agent.memory[-1]["content"] == "测试事件"

    def test_memory_starts_with_system_prompt(self):
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent
        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)
        assert len(agent.memory) >= 1
        assert agent.memory[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_summarize_skips_on_odd_turns(self):
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent
        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)
        agent.turn_count = 1
        initial_len = len(agent.memory)
        await agent.summarize()
        assert len(agent.memory) == initial_len

    @pytest.mark.asyncio
    async def test_summarize_skips_when_memory_small(self):
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent
        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)
        agent.turn_count = 2
        initial_len = len(agent.memory)
        await agent.summarize()
        assert len(agent.memory) == initial_len


class TestPlayerAgentDecide:
    @pytest.mark.asyncio
    async def test_decide_valid_format(self):
        """正常格式 → 返回正确的 ActionResult。"""
        state = make_state([Role.VILLAGER, Role.WEREWOLF, Role.SEER] + [Role.VILLAGER] * 9)
        from src.agent.player import PlayerAgent

        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="【行动】VOTE 2【发言】我怀疑2号"))]

        with patch.object(agent._client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await agent.decide("VOTE", {})

        assert result.action == "VOTE"
        assert result.target_id == 2
        assert "2号" in result.speech or result.speech == "我怀疑2号"

    @pytest.mark.asyncio
    async def test_decide_retry_on_bad_format(self):
        """第一次格式错误 → 重试成功。"""
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent

        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)

        bad_response = Mock()
        bad_response.choices = [Mock(message=Mock(content="我认为3号是狼（无格式标签）"))]
        good_response = Mock()
        good_response.choices = [Mock(message=Mock(content="【行动】VOTE 3"))]

        with patch.object(agent._client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = [bad_response, good_response]
            result = await agent.decide("VOTE", {})

        assert result.action == "VOTE"
        assert result.target_id == 3
        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_decide_fallback_after_two_failures(self):
        """两次格式都错误 → 兜底随机行动。"""
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent

        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)

        bad1 = Mock()
        bad1.choices = [Mock(message=Mock(content="纯文本无标签"))]
        bad2 = Mock()
        bad2.choices = [Mock(message=Mock(content="还是没标签"))]

        with patch.object(agent._client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = [bad1, bad2]
            result = await agent.decide("VOTE", {})

        assert result.action == "VOTE"
        assert result.raw_response == "[FALLBACK]"
        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_decide_skip_action(self):
        """LLM 返回 SKIP → action 为 SKIP。"""
        state = make_state([Role.WITCH, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent

        agent = PlayerAgent(2, "witch", {"model": "test", "api_key": "test"}, state)

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="【行动】SKIP"))]

        with patch.object(agent._client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            result = await agent.decide("WITCH_ACTION", {
                "dead_player": 3, "save_available": True, "poison_available": True
            })

        assert result.action == "SKIP"
        assert result.target_id == 0

    @pytest.mark.asyncio
    async def test_speak_extracts_speech_tag(self):
        state = make_state([Role.VILLAGER, Role.WEREWOLF] + [Role.VILLAGER] * 10)
        from src.agent.player import PlayerAgent

        agent = PlayerAgent(1, "villager", {"model": "test", "api_key": "test"}, state)

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="【发言】我认为2号是狼人，建议投票放逐"))]

        with patch.object(agent._client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response
            speech = await agent.speak({"phase": "DAY_SPEECH"})

        assert "2号" in speech
        assert "我认为2号是狼人" in speech

    def test_werewolf_has_teammate_context(self):
        """狼人 agent 的系统 prompt 包含队友信息。"""
        state = make_state([Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF,
                            Role.SEER, Role.WITCH, Role.HUNTER, Role.FOOL,
                            Role.VILLAGER, Role.VILLAGER, Role.VILLAGER, Role.VILLAGER])
        from src.agent.player import PlayerAgent

        agent = PlayerAgent(1, "werewolf", {"model": "test", "api_key": "test"}, state)
        system_prompt = agent.memory[0]["content"]

        # 应该包含队友信息（2号、3号、4号中的至少两个）
        teammate_count = sum(1 for tid in [2, 3, 4] if f"{tid}号" in system_prompt)
        assert teammate_count >= 2

    def test_retry_message_not_empty(self):
        msg = get_retry_message()
        assert "【行动】" in msg
        assert len(msg) > 10
