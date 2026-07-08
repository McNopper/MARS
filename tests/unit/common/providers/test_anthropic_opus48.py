"""Unit tests for first-class Claude integration in the Anthropic provider.

Covers:
- Opus 4.8 present in the catalogue and on the adaptive-thinking path.
- Default model / max_tokens.
- Thinking-block round-trip: signature captured on parse and the signed
  thinking block replayed first on an assistant tool-use turn (required by
  Anthropic interleaved thinking).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from mars.server.services.llm.anthropic import AnthropicService
from mars.server.services.llm.base import LLMMessage


@pytest.fixture
def anthropic_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    class _Messages:
        async def create(self, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="ok")],
                stop_reason="end_turn",
            )

    class _AsyncAnthropic:
        def __init__(self, api_key: str, **kwargs: object) -> None:
            self.api_key = api_key
            self.max_retries = kwargs.get("max_retries")
            self.messages = _Messages()

    import mars.server.services.llm.anthropic as _anthro_mod
    monkeypatch.setattr(_anthro_mod, "anthropic", SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))
    return calls


def test_opus_4_8_in_catalogue() -> None:
    info = AnthropicService.KNOWN_MODELS.get("claude-opus-4-8")
    assert info is not None
    assert info.context_window == 200_000
    assert info.supports_tools is True


def test_defaults() -> None:
    provider = AnthropicService(api_key="test-key")
    assert provider.model == "claude-sonnet-4-6"
    assert provider._max_tokens == 8192


@pytest.mark.asyncio
async def test_opus_4_8_uses_adaptive_thinking(anthropic_calls: list[dict]) -> None:
    provider = AnthropicService(api_key="test-key", model="claude-opus-4-8", thinking=True)
    await provider.complete([LLMMessage(role="user", content="hi")])
    call = anthropic_calls[-1]
    assert call["thinking"] == {"type": "adaptive"}
    assert "effort" not in call
    assert call["extra_headers"]["anthropic-beta"] == "interleaved-thinking-2025-05-14"


def test_parse_response_captures_thinking_signature() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="weigh options", signature="sig-abc"),
            SimpleNamespace(type="tool_use", id="t1", name="get_time", input={}),
        ],
        stop_reason="tool_use",
    )
    parsed = AnthropicService._parse_response(response)
    assert parsed.thinking == "weigh options"
    assert parsed.thinking_signature == "sig-abc"
    assert parsed.finish_reason == "tool_calls"
    assert parsed.tool_calls and parsed.tool_calls[0]["function"]["name"] == "get_time"


def test_convert_messages_replays_signed_thinking_on_tool_turn() -> None:
    provider = AnthropicService(api_key="test-key")
    assistant = LLMMessage(
        role="assistant",
        content="let me check",
        tool_calls=[{"id": "t1", "function": {"name": "get_time", "arguments": "{}"}}],
        thinking="weigh options",
        thinking_signature="sig-abc",
    )
    _system, messages = provider._convert_messages([
        LLMMessage(role="user", content="what time is it?"),
        assistant,
    ])
    blocks = messages[-1]["content"]
    # The signed thinking block must come first, before text and tool_use.
    assert blocks[0] == {"type": "thinking", "thinking": "weigh options", "signature": "sig-abc"}
    assert blocks[1]["type"] == "text"
    assert blocks[2]["type"] == "tool_use"


def test_convert_messages_replays_signed_empty_thinking() -> None:
    # Adaptive thinking returns a signed block whose text is empty; the signed
    # block must still be replayed (keyed on the signature) for the API to
    # validate the chain across tool rounds.
    provider = AnthropicService(api_key="test-key")
    assistant = LLMMessage(
        role="assistant",
        content="the answer",
        tool_calls=[{"id": "t1", "function": {"name": "get_time", "arguments": "{}"}}],
        thinking=None,
        thinking_signature="sig-xyz",
    )
    _system, messages = provider._convert_messages([assistant])
    assert messages[-1]["content"][0] == {
        "type": "thinking", "thinking": "", "signature": "sig-xyz",
    }


def test_convert_messages_omits_thinking_without_signature() -> None:
    provider = AnthropicService(api_key="test-key")
    assistant = LLMMessage(
        role="assistant",
        content="answer",
        tool_calls=[{"id": "t1", "function": {"name": "get_time", "arguments": "{}"}}],
        thinking="unsigned reasoning",  # no signature → must NOT be replayed
    )
    _system, messages = provider._convert_messages([assistant])
    blocks = messages[-1]["content"]
    assert all(b["type"] != "thinking" for b in blocks)
