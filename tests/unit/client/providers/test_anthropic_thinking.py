from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from mars.client.providers.anthropic import AnthropicProvider
from mars.client.providers.base import LLMMessage


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
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.messages = _Messages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=_AsyncAnthropic))
    return calls


@pytest.mark.asyncio
async def test_manual_thinking_config_is_forwarded(anthropic_calls: list[dict]) -> None:
    provider = AnthropicProvider(
        api_key="test-key",
        thinking=True,
        thinking_budget=2_048,
        max_tokens=1_024,
    )

    await provider.complete([LLMMessage(role="user", content="hello")])

    call = anthropic_calls[-1]
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 2_048}
    assert call["max_tokens"] == 3_072


@pytest.mark.asyncio
async def test_adaptive_thinking_config_is_forwarded(anthropic_calls: list[dict]) -> None:
    provider = AnthropicProvider(
        api_key="test-key",
        model="claude-sonnet-4-6",
        effort="high",
    )

    await provider.complete([LLMMessage(role="user", content="hello")])

    call = anthropic_calls[-1]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["effort"] == "high"
    assert call["extra_headers"]["anthropic-beta"] == "interleaved-thinking-2025-05-14"


def test_parse_response_handles_thinking_blocks() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="consider options"),
            SimpleNamespace(type="text", text="final answer"),
        ],
        stop_reason="end_turn",
    )

    parsed_without = AnthropicProvider._parse_response(response)
    parsed_with = AnthropicProvider._parse_response(response, include_thinking=True)

    assert parsed_without.content == "final answer"
    assert parsed_with.content == "[Thinking]\nconsider options\n[/Thinking]\nfinal answer"


def test_cache_prompts_marks_last_system_block(anthropic_calls: list[dict]) -> None:
    provider = AnthropicProvider(api_key="test-key", cache_prompts=True)

    system, messages = provider._convert_messages(
        [
            LLMMessage(role="system", content="static instructions"),
            LLMMessage(role="system", content="cached footer"),
            LLMMessage(role="user", content="hello"),
        ]
    )

    assert messages == [{"role": "user", "content": "hello"}]
    assert system == [
        {"type": "text", "text": "static instructions"},
        {
            "type": "text",
            "text": "cached footer",
            "cache_control": {"type": "ephemeral"},
        },
    ]
