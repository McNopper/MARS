"""Unit tests for the Ollama native /api/chat path and num_ctx.

Regression guard for the local-model context bug: Ollama's OpenAI-compatible
/v1 endpoint silently ignores the context window (always 4096), truncating the
large prompts MARS workflows send. The provider now uses the native /api/chat
endpoint, which honours options.num_ctx, and translates tool calls to/from the
OpenAI wire shape the agent layer expects.
"""
from __future__ import annotations

from typing import Any

import pytest

from mars.server.services.llm.base import LLMMessage
from mars.server.services.llm.ollama import OllamaService

pytestmark = pytest.mark.unit


def test_num_ctx_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert OllamaService(model="llama3.2")._num_ctx == 16384
    monkeypatch.setenv("MARS_OLLAMA_NUM_CTX", "32768")
    assert OllamaService(model="llama3.2")._num_ctx == 32768
    assert OllamaService(model="llama3.2", num_ctx=2048)._num_ctx == 2048


def test_to_ollama_message_tool_result_uses_tool_name() -> None:
    m = LLMMessage(role="tool", content="42", tool_call_id="x", name="calc")
    assert OllamaService._to_ollama_message(m) == {
        "role": "tool", "content": "42", "tool_name": "calc",
    }


def test_to_ollama_message_assistant_arguments_become_object() -> None:
    # OpenAI wire stores arguments as a JSON string; Ollama wants an object.
    m = LLMMessage(
        role="assistant", content="",
        tool_calls=[{"id": "1", "function": {"name": "calc", "arguments": '{"expr": "6*7"}'}}],
    )
    out = OllamaService._to_ollama_message(m)
    assert out["tool_calls"][0]["function"]["arguments"] == {"expr": "6*7"}


def test_parse_response_reencodes_arguments_as_string() -> None:
    data = {
        "message": {"content": "", "tool_calls": [
            {"function": {"name": "calc", "arguments": {"expr": "6*7"}}}
        ]},
        "done_reason": "stop",
    }
    resp = OllamaService._parse_ollama_response(data)
    tc = resp.tool_calls[0]
    assert tc["function"]["name"] == "calc"
    assert tc["function"]["arguments"] == '{"expr": "6*7"}'   # JSON string for the agent layer
    assert tc["id"]                                            # synthesised when Ollama omits it


@pytest.mark.asyncio
async def test_complete_sends_num_ctx_to_native_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict[str, Any]:
            return {"message": {"content": "hi", "tool_calls": []}, "done_reason": "stop"}

    class _Client:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        async def __aenter__(self) -> "_Client": return self
        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, json: dict[str, Any]) -> _Resp:  # noqa: A002
            captured["url"] = url
            captured["payload"] = json
            return _Resp()

    import mars.server.services.llm.ollama as omod
    monkeypatch.setattr(omod.httpx, "AsyncClient", _Client)

    p = OllamaService(model="qwen2.5:7b", num_ctx=8192)
    resp = await p.complete([LLMMessage(role="user", content="hello")])

    assert captured["url"].endswith("/api/chat")
    assert captured["payload"]["options"]["num_ctx"] == 8192
    assert captured["payload"]["stream"] is False
    assert resp.content == "hi"
