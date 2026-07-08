"""Anthropic Claude provider adapter for MARS.

Uses the native ``anthropic`` SDK. Key differences from OpenAI-compatible
providers:

* The ``system`` prompt is a top-level parameter, not a message.
* Tool definitions use ``input_schema`` instead of ``parameters``.
* Tool results are ``user`` turns with ``tool_result`` content blocks.
* Multiple tool results must be batched into a single ``user`` message to
  satisfy Anthropic's strict alternating-role requirement.
* ``max_tokens`` is mandatory in every request.

Install: pip install anthropic
API key: https://console.anthropic.com → API Keys → Create Key

Available models (June 2026)
----------------------------
  claude-opus-4-8             – Latest flagship, adaptive thinking (1M-context beta available)
  claude-opus-4-7             – Most capable previous Opus, adaptive thinking
  claude-opus-4-6             – Very capable, adaptive thinking recommended
  claude-sonnet-4-6           – Balanced capability / speed (default)
  claude-haiku-4-5            – Fastest, lightest
  claude-opus-4-5             – Previous generation flagship
  claude-sonnet-4-5           – Previous generation balanced tier
  claude-3-5-sonnet-20241022  – Legacy widely deployed Sonnet
  claude-3-5-haiku-20241022   – Legacy fast tier
  claude-3-opus-20240229      – Legacy max capability
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic  # type: ignore[import]

from mars.server.services.llm.base import LLMProvider, LLMMessage, LLMResponse, ModelInfo, ToolSpec, env_int

logger = logging.getLogger(__name__)

# Beta header that lets thinking interleave with tool use (so the model keeps
# its reasoning across tool-call rounds).  Accepted by the current API.
_INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"
# Thinking config differs per model (verified against the live API):
#   * Opus 4.x and Sonnet 4.6 require ``thinking={"type": "adaptive"}``
#     ("enabled" is rejected for Opus).
#   * Haiku and legacy models use ``thinking={"type": "enabled", "budget_tokens"}``.
# There is no ``effort`` field — the API rejects it — so MARS does not expose one.
_ADAPTIVE_THINKING_MODELS = frozenset({
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-opus-4-5",
    "claude-sonnet-4-6",
})
_MODELS: list[ModelInfo] = [
    ModelInfo(
        "claude-opus-4-8",
        "Claude Opus 4.8",
        "Anthropic – latest flagship, adaptive thinking (1M-context beta available)",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-opus-4-7",
        "Claude Opus 4.7",
        "Anthropic – most capable previous Opus, adaptive thinking",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-opus-4-6",
        "Claude Opus 4.6",
        "Anthropic – very capable, adaptive thinking recommended",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-sonnet-4-6",
        "Claude Sonnet 4.6",
        "Anthropic – balanced capability and speed",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        "Anthropic – fastest and most compact",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-opus-4-5",
        "Claude Opus 4.5",
        "Anthropic – previous generation flagship",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-sonnet-4-5",
        "Claude Sonnet 4.5",
        "Anthropic – previous generation balanced tier",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-3-5-sonnet-20241022",
        "Claude 3.5 Sonnet",
        "Anthropic – legacy widely deployed Sonnet tier",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-3-5-haiku-20241022",
        "Claude 3.5 Haiku",
        "Anthropic – legacy fast tier",
        200_000,
        supports_tools=True,
    ),
    ModelInfo(
        "claude-3-opus-20240229",
        "Claude 3 Opus",
        "Anthropic – legacy max capability",
        200_000,
        supports_tools=True,
    ),
]

_DEFAULT_MAX_TOKENS = 8192
_DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicService(LLMProvider):
    """Anthropic Claude provider using the native ``anthropic`` SDK.

    Parameters
    ----------
    model:
        Anthropic model ID, e.g. ``"claude-sonnet-4-6"``.
        Defaults to ``"claude-sonnet-4-6"``.
    api_key:
        Anthropic API key. If omitted, reads ``ANTHROPIC_API_KEY`` or
        ``ANTHROPIC_KEY`` from the environment.
    max_tokens:
        Maximum tokens to generate per completion (Anthropic requires this
        field). Default: 8192.
    thinking:
        Enable extended thinking.  The supported config is chosen automatically
        per model (adaptive for Opus 4.x / Sonnet 4.6, budgeted "enabled" for
        the rest); interleaved-thinking is always requested so reasoning
        survives tool-call rounds.
    thinking_budget:
        Reasoning-token budget for models that use "enabled" thinking.
    cache_prompts:
        Enable prompt caching on the last static system block.
    default_params:
        Extra keyword arguments forwarded to every ``messages.create`` call
        (e.g. ``temperature=0.7``).
    """

    provider_name = "anthropic"
    KNOWN_MODELS: dict[str, ModelInfo] = {m.id: m for m in _MODELS}

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        thinking: bool = False,
        thinking_budget: int = 10_000,
        cache_prompts: bool = False,
        default_params: dict[str, Any] | None = None,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY")
        if not key:
            raise ValueError(
                "Anthropic requires an API key.\n\n"
                "  1. Go to https://console.anthropic.com\n"
                "  2. Click 'API Keys' → 'Create Key'\n"
                "  3. Add to .env:  ANTHROPIC_API_KEY=sk-ant-...\n"
                "     (ANTHROPIC_KEY is also accepted)\n"
            )

        self._model = model
        self._max_tokens = max_tokens
        self._thinking = thinking
        self._thinking_budget = thinking_budget
        self._cache_prompts = cache_prompts
        self._default_params: dict[str, Any] = default_params or {}
        # Retry transient 429/5xx/connection errors with exponential backoff
        # instead of failing the agent on the first blip (see MARS_LLM_MAX_RETRIES).
        self._client = anthropic.AsyncAnthropic(
            api_key=key,
            max_retries=env_int("MARS_LLM_MAX_RETRIES", 5),
        )

    # ------------------------------------------------------------------
    # LLMService implementation
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        include_thinking = bool(kwargs.pop("include_thinking", False))
        system, anthropic_messages = self._convert_messages(messages)

        call_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": anthropic_messages,
            **self._default_params,
            **kwargs,
        }
        if system:
            call_kwargs["system"] = system
        if tools:
            call_kwargs["tools"] = [self._tool_schema(t) for t in tools]

        if self._thinking:
            # Pick the thinking config this model actually accepts.
            if self._model in _ADAPTIVE_THINKING_MODELS:
                call_kwargs["thinking"] = {"type": "adaptive"}
            else:
                budget = self._thinking_budget
                call_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                call_kwargs["max_tokens"] = max(
                    int(call_kwargs.get("max_tokens", self._max_tokens)),
                    budget + 1024,
                )
            # Interleaved thinking keeps reasoning coherent across tool rounds.
            call_kwargs["extra_headers"] = self._merge_extra_headers(
                call_kwargs.get("extra_headers"),
                {"anthropic-beta": _INTERLEAVED_THINKING_BETA},
            )

        logger.debug(
            "%s.complete model=%s msgs=%d tools=%d",
            self.__class__.__name__,
            self._model,
            len(anthropic_messages),
            len(tools) if tools else 0,
        )

        response = await self._client.messages.create(**call_kwargs)
        return self._parse_response(response, include_thinking=include_thinking)

    async def list_models(self) -> list[ModelInfo]:
        return list(self.KNOWN_MODELS.values())

    # ------------------------------------------------------------------
    # Message conversion helpers
    # ------------------------------------------------------------------

    def _convert_messages(
        self,
        messages: list[LLMMessage],
    ) -> tuple[str | list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert MARS messages to Anthropic API format.

        Returns ``(system_prompt, anthropic_messages)``.

        Anthropic-specific rules applied:
        * ``system`` role messages are extracted into the top-level ``system`` parameter.
        * ``tool`` role messages become ``user`` turns containing
          ``tool_result`` content blocks. Consecutive tool results are
          batched into a single user message (required by Anthropic).
        * ``assistant`` turns with tool calls are serialised as a list of
          ``text`` + ``tool_use`` content blocks.
        """
        system_parts: list[str] = []
        result: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
                continue

            if msg.role == "tool":
                block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content or "",
                }
                if (
                    result
                    and result[-1]["role"] == "user"
                    and isinstance(result[-1]["content"], list)
                    and any(b.get("type") == "tool_result" for b in result[-1]["content"])
                ):
                    result[-1]["content"].append(block)
                else:
                    result.append({"role": "user", "content": [block]})
                continue

            if msg.role == "assistant" and msg.tool_calls:
                content_blocks: list[dict[str, Any]] = []
                # When interleaved thinking is active, the signed thinking block
                # must be replayed FIRST (before text/tool_use) on the assistant
                # turn so the API can validate the reasoning chain across rounds.
                # Adaptive thinking returns a *signed but empty-text* block (the
                # summary lands in the text block), so key on the signature — the
                # field the API actually validates — and send the text as-is.
                if msg.thinking_signature:
                    content_blocks.append({
                        "type": "thinking",
                        "thinking": msg.thinking or "",
                        "signature": msg.thinking_signature,
                    })
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            parsed_args: Any = json.loads(raw_args)
                        except json.JSONDecodeError:
                            parsed_args = {}
                    else:
                        parsed_args = raw_args
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": fn.get("name", ""),
                            "input": parsed_args,
                        }
                    )
                result.append({"role": "assistant", "content": content_blocks})
                continue

            result.append({"role": msg.role, "content": msg.content or ""})

        if not system_parts:
            return "", result
        if not self._cache_prompts:
            return "\n".join(system_parts), result

        system_blocks = [{"type": "text", "text": part} for part in system_parts if part]
        if system_blocks:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}
        return system_blocks, result

    @staticmethod
    def _tool_schema(tool: ToolSpec) -> dict[str, Any]:
        """Serialise a ToolSpec to the Anthropic tool definition format."""
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }

    @staticmethod
    def _merge_extra_headers(
        current: dict[str, str] | None,
        updates: dict[str, str],
    ) -> dict[str, str]:
        merged = dict(current or {})
        for key, value in updates.items():
            existing_key = next((candidate for candidate in merged if candidate.lower() == key.lower()), key)
            if existing_key.lower() == "anthropic-beta" and existing_key in merged:
                existing = merged[existing_key]
                existing_values = [item.strip() for item in existing.split(",") if item.strip()]
                if value not in existing_values:
                    existing_values.append(value)
                merged[existing_key] = ",".join(existing_values)
            else:
                merged[existing_key] = value
        return merged

    @staticmethod
    def _block_field(block: Any, name: str, default: Any = None) -> Any:
        if isinstance(block, dict):
            return block.get(name, default)
        return getattr(block, name, default)

    @classmethod
    def _parse_response(
        cls,
        response: Any,
        *,
        include_thinking: bool = False,
    ) -> LLMResponse:
        """Parse an Anthropic ``Message`` into a MARS ``LLMResponse``."""
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        # First thinking block's signature — Anthropic requires the signed
        # thinking block be replayed verbatim on the next tool-use turn.
        thinking_signature: str | None = None

        for block in cls._block_field(response, "content", []):
            block_type = cls._block_field(block, "type")
            if block_type == "text":
                text = cls._block_field(block, "text")
                if text:
                    text_parts.append(text)
            elif block_type == "thinking":
                thinking = cls._block_field(block, "thinking") or cls._block_field(block, "text")
                if thinking:
                    thinking_parts.append(thinking)
                if thinking_signature is None:
                    sig = cls._block_field(block, "signature")
                    if sig:
                        thinking_signature = sig
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": cls._block_field(block, "id", ""),
                        "type": "function",
                        "function": {
                            "name": cls._block_field(block, "name", ""),
                            "arguments": json.dumps(cls._block_field(block, "input", {})),
                        },
                    }
                )

        text_content = "\n".join(text_parts).strip()
        # Raw thinking (unprefixed) is preserved for replay across tool rounds,
        # independently of the human-facing include_thinking display option.
        raw_thinking = "\n\n".join(thinking_parts).strip() or None
        if include_thinking and thinking_parts:
            thinking_prefix = f"[Thinking]\n{raw_thinking}\n[/Thinking]"
            text_content = f"{thinking_prefix}\n{text_content}" if text_content else thinking_prefix

        content = text_content or None

        stop_reason = cls._block_field(response, "stop_reason") or "end_turn"
        if stop_reason == "end_turn":
            stop_reason = "stop"
        elif stop_reason == "tool_use":
            stop_reason = "tool_calls"

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=stop_reason,
            thinking=raw_thinking,
            thinking_signature=thinking_signature,
            raw=response,
        )
