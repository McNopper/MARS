"""OpenAI-compatible provider base.

All providers whose API follows the OpenAI chat-completions schema inherit
from ``OpenAICompatibleProvider``.  The full message/tool serialisation and
response parsing is implemented once here; thin subclasses only set defaults
(base_url, model, extra headers, etc.).

Supported by this base:
  OpenAI, Azure OpenAI, Groq, Ollama, LM Studio, OpenRouter,
  Together AI, Fireworks AI, Perplexity AI, xAI (Grok),
  DeepSeek, Cerebras, NVIDIA NIM, Cloudflare Workers AI,
  HuggingFace TGI, Mistral AI
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI  # type: ignore[import]

from mars.server.services.llm.base import LLMMessage, LLMProvider, LLMResponse, ToolSpec, env_int

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Reusable adapter for any OpenAI chat-completions compatible API.

    Parameters
    ----------
    model:
        Model identifier string (vendor-specific).
    api_key:
        API key / token.  Pass ``"ollama"`` or any dummy value for
        providers that do not require authentication.
    base_url:
        API base URL.  Defaults to the official OpenAI endpoint.
    default_params:
        Extra keyword arguments forwarded to every ``create`` call
        (e.g. ``temperature=0.7``, ``max_tokens=2048``).
    extra_headers:
        HTTP headers added to every request (e.g. ``HTTP-Referer`` for
        OpenRouter).
    """

    provider_name = "openai-compatible"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        default_params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._default_params: dict[str, Any] = default_params or {}
        # max_retries lets the SDK ride out transient 429 (rate-limit throttle),
        # 5xx, and connection errors with exponential backoff + Retry-After,
        # instead of the agent dying on the first blip. (Hard quota-exhaustion
        # 429s are not transient and will still surface after the retries.)
        self._client = AsyncOpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url,
            default_headers=extra_headers or {},
            max_retries=env_int("MARS_LLM_MAX_RETRIES", 5),
        )

    # ------------------------------------------------------------------
    # LLMProvider implementation
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        oai_messages = [self._to_oai_message(m) for m in messages]
        call_kwargs: dict[str, Any] = {**self._default_params, **kwargs}

        if tools:
            call_kwargs["tools"] = [self._tool_schema(t) for t in tools]
            call_kwargs["tool_choice"] = call_kwargs.pop("tool_choice", "auto")

        logger.debug(
            "%s.complete model=%s msgs=%d tools=%d",
            self.__class__.__name__,
            self._model,
            len(oai_messages),
            len(tools) if tools else 0,
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,  # type: ignore[arg-type]
            **call_kwargs,
        )
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_oai_message(m: LLMMessage) -> dict[str, Any]:
        if m.role == "tool":
            return {
                "role": "tool",
                "content": m.content or "",
                "tool_call_id": m.tool_call_id or "",
            }
        if m.tool_calls:
            return {
                "role": "assistant",
                "content": m.content,
                "tool_calls": m.tool_calls,
            }
        return {"role": m.role, "content": m.content or ""}

    @staticmethod
    def _tool_schema(tool: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            raw=response,
        )
