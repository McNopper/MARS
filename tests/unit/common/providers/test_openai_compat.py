"""Unit tests for OpenAICompatibleProvider static helpers.

These helpers (_to_oai_message, _tool_schema, _parse_response) are
static methods that contain no I/O. They are tested here by importing
only the class definition, not the full provider.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any


# We patch the openai import to avoid requiring the package in unit tests.
import sys
import types

_fake_openai = types.ModuleType("openai")
_fake_openai.AsyncOpenAI = lambda **kw: None  # type: ignore[attr-defined]
sys.modules.setdefault("openai", _fake_openai)

from mars.server.services.llm._openai_compat import OpenAICompatibleProvider  # noqa: E402
from mars.server.services.llm.base import LLMMessage  # noqa: E402


# ---------------------------------------------------------------------------
# _to_oai_message
# ---------------------------------------------------------------------------

class TestToOaiMessage:
    def _user(self, content: str) -> LLMMessage:
        return LLMMessage(role="user", content=content)

    def _assistant(self, content: str | None, tool_calls=None) -> LLMMessage:
        return LLMMessage(role="assistant", content=content, tool_calls=tool_calls)

    def _tool(self, content: str, tc_id: str) -> LLMMessage:
        return LLMMessage(role="tool", content=content, tool_call_id=tc_id)

    def test_user_message(self) -> None:
        result = OpenAICompatibleProvider._to_oai_message(self._user("hello"))
        assert result == {"role": "user", "content": "hello"}

    def test_system_message(self) -> None:
        msg = LLMMessage(role="system", content="You are a helpful assistant.")
        result = OpenAICompatibleProvider._to_oai_message(msg)
        assert result == {"role": "system", "content": "You are a helpful assistant."}

    def test_tool_result_message(self) -> None:
        result = OpenAICompatibleProvider._to_oai_message(self._tool("42", "call_abc"))
        assert result == {"role": "tool", "content": "42", "tool_call_id": "call_abc"}

    def test_tool_result_none_id_becomes_empty(self) -> None:
        msg = LLMMessage(role="tool", content="ok", tool_call_id=None)
        result = OpenAICompatibleProvider._to_oai_message(msg)
        assert result["tool_call_id"] == ""

    def test_assistant_with_tool_calls_includes_them(self) -> None:
        tc = [{"id": "call_1", "type": "function",
               "function": {"name": "my_fn", "arguments": "{}"}}]
        msg = self._assistant("Calling tool", tool_calls=tc)
        result = OpenAICompatibleProvider._to_oai_message(msg)
        assert result["role"] == "assistant"
        assert result["tool_calls"] == tc

    def test_assistant_without_tool_calls(self) -> None:
        msg = self._assistant("Plain response")
        result = OpenAICompatibleProvider._to_oai_message(msg)
        assert result == {"role": "assistant", "content": "Plain response"}

    def test_none_content_becomes_empty_string(self) -> None:
        msg = LLMMessage(role="user", content=None)
        result = OpenAICompatibleProvider._to_oai_message(msg)
        assert result["content"] == ""


# ---------------------------------------------------------------------------
# _tool_schema
# ---------------------------------------------------------------------------

class _FakeTool:
    """Minimal ToolSpec implementation for testing."""
    def __init__(self, name: str, description: str, parameters: dict) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters


class TestToolSchema:
    def test_wraps_in_function_type(self) -> None:
        tool = _FakeTool("add", "Add two numbers.", {"type": "object",
                                                       "properties": {}})
        schema = OpenAICompatibleProvider._tool_schema(tool)
        assert schema["type"] == "function"

    def test_function_name(self) -> None:
        tool = _FakeTool("my_tool", "Does stuff.", {"type": "object"})
        schema = OpenAICompatibleProvider._tool_schema(tool)
        assert schema["function"]["name"] == "my_tool"

    def test_function_description(self) -> None:
        tool = _FakeTool("t", "My description.", {"type": "object"})
        schema = OpenAICompatibleProvider._tool_schema(tool)
        assert schema["function"]["description"] == "My description."

    def test_function_parameters_passed_through(self) -> None:
        params = {"type": "object", "properties": {"x": {"type": "integer"}},
                  "required": ["x"]}
        tool = _FakeTool("fn", "fn", params)
        schema = OpenAICompatibleProvider._tool_schema(tool)
        assert schema["function"]["parameters"] == params


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

def _fake_response(
    content: str | None,
    finish_reason: str = "stop",
    tool_calls: list | None = None,
) -> Any:
    """Build a minimal fake OpenAI response object."""
    tc_objs = []
    if tool_calls:
        for tc in tool_calls:
            tc_obj = SimpleNamespace(
                id=tc["id"],
                function=SimpleNamespace(
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                ),
            )
            tc_objs.append(tc_obj)

    msg = SimpleNamespace(
        content=content,
        tool_calls=tc_objs if tc_objs else None,
    )
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class TestParseResponse:
    def test_plain_content(self) -> None:
        resp = _fake_response("Hello world")
        result = OpenAICompatibleProvider._parse_response(resp)
        assert result.content == "Hello world"
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    def test_finish_reason_forwarded(self) -> None:
        resp = _fake_response("ok", finish_reason="length")
        result = OpenAICompatibleProvider._parse_response(resp)
        assert result.finish_reason == "length"

    def test_none_finish_reason_defaults_to_stop(self) -> None:
        resp = _fake_response("ok", finish_reason=None)
        result = OpenAICompatibleProvider._parse_response(resp)
        assert result.finish_reason == "stop"

    def test_tool_calls_parsed(self) -> None:
        tcs = [{"id": "call_x", "function": {"name": "add",
                                               "arguments": '{"a":1,"b":2}'}}]
        resp = _fake_response(None, finish_reason="tool_calls", tool_calls=tcs)
        result = OpenAICompatibleProvider._parse_response(resp)
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc["id"] == "call_x"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "add"
        assert tc["function"]["arguments"] == '{"a":1,"b":2}'

    def test_multiple_tool_calls(self) -> None:
        tcs = [
            {"id": "c1", "function": {"name": "fn1", "arguments": "{}"}},
            {"id": "c2", "function": {"name": "fn2", "arguments": "{}"}},
        ]
        resp = _fake_response(None, finish_reason="tool_calls", tool_calls=tcs)
        result = OpenAICompatibleProvider._parse_response(resp)
        assert len(result.tool_calls) == 2

    def test_raw_response_attached(self) -> None:
        fake = _fake_response("hi")
        result = OpenAICompatibleProvider._parse_response(fake)
        assert result.raw is fake
