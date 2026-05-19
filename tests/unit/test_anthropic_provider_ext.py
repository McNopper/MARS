"""Extended unit tests for mars.providers.anthropic.AnthropicProvider.

Covers:
- Constructor validates API key and effort parameter
- _convert_messages: extracts system prompt, batches tool results, serialises tool calls
- _tool_schema: uses input_schema field name
- _parse_response: maps tool_use blocks and finish reasons
- _merge_extra_headers: anthropic-beta deduplication
"""
from __future__ import annotations

import json
import os
import unittest.mock as mock

import pytest

from mars.providers.base import LLMMessage, LLMResponse, ToolSpec

# Skip the entire file if the anthropic SDK is not installed
pytest.importorskip("anthropic", reason="anthropic package not installed")


# ---------------------------------------------------------------------------
# Helpers – build the provider without hitting the real Anthropic SDK
# ---------------------------------------------------------------------------


def _make_provider(
    api_key: str = "sk-ant-test",
    **kwargs,
):
    """Construct an AnthropicProvider with a patched SDK client."""
    with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": api_key}):
        with mock.patch("anthropic.AsyncAnthropic"):
            from mars.providers.anthropic import AnthropicProvider
            return AnthropicProvider(api_key=api_key, **kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestAnthropicProviderConstruction:
    def test_init_requires_api_key(self) -> None:
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in {"ANTHROPIC_API_KEY", "ANTHROPIC_KEY"}}
        with mock.patch.dict(os.environ, clean_env, clear=True):
            with mock.patch("anthropic.AsyncAnthropic"):
                from mars.providers.anthropic import AnthropicProvider
                with pytest.raises(ValueError, match="API key"):
                    AnthropicProvider(api_key=None)

    def test_init_reads_api_key_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-from-env"}):
            with mock.patch("anthropic.AsyncAnthropic") as mock_client:
                from mars.providers.anthropic import AnthropicProvider
                AnthropicProvider()
                mock_client.assert_called_once_with(api_key="sk-from-env")

    def test_init_rejects_invalid_effort(self) -> None:
        with pytest.raises(ValueError, match="effort"):
            _make_provider(effort="ultra")

    def test_init_accepts_valid_efforts(self) -> None:
        for effort in ("low", "medium", "high"):
            p = _make_provider(effort=effort)
            assert p._effort == effort


# ---------------------------------------------------------------------------
# _convert_messages
# ---------------------------------------------------------------------------


class TestConvertMessages:
    def _provider(self):
        return _make_provider()

    def test_extracts_system_prompt(self) -> None:
        p = self._provider()
        messages = [
            LLMMessage(role="system", content="You are a helpful assistant."),
            LLMMessage(role="user", content="Hello"),
        ]
        system, result = p._convert_messages(messages)
        assert system == "You are a helpful assistant."
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_no_system_returns_empty_string(self) -> None:
        p = self._provider()
        messages = [LLMMessage(role="user", content="Hi")]
        system, result = p._convert_messages(messages)
        assert system == ""

    def test_batches_tool_results_into_one_user_turn(self) -> None:
        p = self._provider()
        messages = [
            LLMMessage(role="tool", content="result1", tool_call_id="tc1"),
            LLMMessage(role="tool", content="result2", tool_call_id="tc2"),
        ]
        _, result = p._convert_messages(messages)
        # Both tool results must be batched into a single user message
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 2
        assert all(b["type"] == "tool_result" for b in result[0]["content"])

    def test_consecutive_tool_results_batched_separate_from_non_consecutive(self) -> None:
        p = self._provider()
        messages = [
            LLMMessage(role="tool", content="r1", tool_call_id="tc1"),
            LLMMessage(role="user", content="new question"),
            LLMMessage(role="tool", content="r2", tool_call_id="tc2"),
        ]
        _, result = p._convert_messages(messages)
        # non-consecutive tool results should NOT be merged
        assert len(result) == 3

    def test_serializes_assistant_tool_calls_as_content_blocks(self) -> None:
        p = self._provider()
        messages = [
            LLMMessage(
                role="assistant",
                content="Let me check.",
                tool_calls=[
                    {
                        "id": "tc_abc",
                        "function": {"name": "search", "arguments": '{"q": "test"}'},
                    }
                ],
            )
        ]
        _, result = p._convert_messages(messages)
        assert result[0]["role"] == "assistant"
        content = result[0]["content"]
        assert any(b["type"] == "text" for b in content)
        tool_use = next(b for b in content if b["type"] == "tool_use")
        assert tool_use["name"] == "search"
        assert tool_use["input"] == {"q": "test"}

    def test_multiple_system_parts_joined(self) -> None:
        p = self._provider()
        messages = [
            LLMMessage(role="system", content="Instruction 1."),
            LLMMessage(role="system", content="Instruction 2."),
            LLMMessage(role="user", content="hi"),
        ]
        system, _ = p._convert_messages(messages)
        assert "Instruction 1." in system
        assert "Instruction 2." in system


# ---------------------------------------------------------------------------
# _tool_schema
# ---------------------------------------------------------------------------


class TestToolSchema:
    def test_uses_input_schema_key(self) -> None:
        from types import SimpleNamespace

        from mars.providers.anthropic import AnthropicProvider

        # ToolSpec is a Protocol — runtime-checkable but not instantiable on
        # Python 3.13+. Build a structural stand-in instead.
        spec = SimpleNamespace(
            name="my_tool",
            description="Does something",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        schema = AnthropicProvider._tool_schema(spec)
        assert schema["name"] == "my_tool"
        assert schema["description"] == "Does something"
        assert "input_schema" in schema
        assert "parameters" not in schema  # OpenAI uses 'parameters'; Anthropic must use 'input_schema'
        assert schema["input_schema"] == spec.parameters


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def _mock_response(content_blocks: list, stop_reason: str = "end_turn"):
    """Build a mock Anthropic response object."""
    resp = mock.MagicMock()
    resp.content = content_blocks
    resp.stop_reason = stop_reason
    return resp


def _text_block(text: str):
    b = mock.MagicMock()
    b.type = "text"
    b.text = text
    return b


def _tool_use_block(tool_id: str, name: str, input_: dict):
    b = mock.MagicMock()
    b.type = "tool_use"
    b.id = tool_id
    b.name = name
    b.input = input_
    return b


class TestParseResponse:
    def test_maps_text_block_to_content(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        resp = _mock_response([_text_block("Hello world")])
        result = AnthropicProvider._parse_response(resp)
        assert result.content == "Hello world"

    def test_maps_tool_use_to_tool_calls(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        resp = _mock_response(
            [_tool_use_block("tc1", "do_thing", {"x": 1})],
            stop_reason="tool_use",
        )
        result = AnthropicProvider._parse_response(resp)
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc["function"]["name"] == "do_thing"
        args = json.loads(tc["function"]["arguments"])
        assert args == {"x": 1}

    def test_finish_reason_end_turn_maps_to_stop(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        resp = _mock_response([_text_block("ok")], stop_reason="end_turn")
        result = AnthropicProvider._parse_response(resp)
        assert result.finish_reason == "stop"

    def test_finish_reason_tool_use_maps_to_tool_calls(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        resp = _mock_response([_tool_use_block("t1", "fn", {})], stop_reason="tool_use")
        result = AnthropicProvider._parse_response(resp)
        assert result.finish_reason == "tool_calls"

    def test_raw_stored_on_response(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        resp = _mock_response([_text_block("hi")])
        result = AnthropicProvider._parse_response(resp)
        assert result.raw is resp


# ---------------------------------------------------------------------------
# _merge_extra_headers
# ---------------------------------------------------------------------------


class TestMergeExtraHeaders:
    def test_merges_new_key(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        result = AnthropicProvider._merge_extra_headers(None, {"X-Custom": "val"})
        assert result["X-Custom"] == "val"

    def test_anthropic_beta_deduplicates_values(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        existing = {"anthropic-beta": "value-a"}
        result = AnthropicProvider._merge_extra_headers(existing, {"anthropic-beta": "value-b"})
        assert "value-a" in result["anthropic-beta"]
        assert "value-b" in result["anthropic-beta"]

    def test_anthropic_beta_does_not_duplicate_same_value(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        existing = {"anthropic-beta": "value-a"}
        result = AnthropicProvider._merge_extra_headers(existing, {"anthropic-beta": "value-a"})
        assert result["anthropic-beta"].count("value-a") == 1

    def test_none_current_treated_as_empty(self) -> None:
        from mars.providers.anthropic import AnthropicProvider
        result = AnthropicProvider._merge_extra_headers(None, {"anthropic-beta": "b1"})
        assert result["anthropic-beta"] == "b1"
