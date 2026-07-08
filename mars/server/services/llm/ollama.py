"""Ollama provider adapter – local, free, no API key required.

Docs: https://ollama.com/
Free tier: Completely free (runs locally).
Tool calling: Yes (model-dependent – llama3, qwen2.5, mistral support it).
OpenAI-compatible: Yes (serves OpenAI-compatible API on localhost:11434).

Install: pip install openai  +  https://ollama.com/download
Start:   ollama serve
Pull:    ollama pull llama3.2

Recommended models:
  llama3.2        – Meta Llama 3.2 3B (fast, small)
  llama3.3        – Meta Llama 3.3 70B (high quality, needs ~40GB RAM)
  qwen2.5:7b      – Alibaba Qwen 2.5 7B (strong, small)
  mistral         – Mistral 7B
  gemma3:4b       – Google Gemma 3 4B
  phi4            – Microsoft Phi-4 (small but capable)
  deepseek-r1:8b  – DeepSeek-R1 reasoning model

Native API notes
----------------
Chat completions go through Ollama's OpenAI-compatible ``/v1`` endpoint.
Model management uses the native Ollama REST API:

  GET  /api/tags        – list locally installed models
  POST /api/pull        – pull a model from the Ollama registry
  POST /api/delete      – remove a model
  GET  /api/ps          – show currently running models
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from mars.server.services.llm._openai_compat import OpenAICompatibleProvider
from mars.server.services.llm.base import LLMMessage, LLMResponse, ModelInfo, ToolSpec, env_int

logger = logging.getLogger(__name__)

# Models known to support tool/function calling via Ollama
_TOOL_CAPABLE = {
    "llama3.1", "llama3.2", "llama3.3",
    "qwen2.5", "qwen2.5-coder",
    "mistral", "mistral-nemo", "mistral-small",
    "mixtral",
    "command-r", "command-r-plus",
    "firefunction-v2",
}


def _supports_tools(model_name: str) -> bool:
    base = model_name.split(":")[0].lower()
    return any(base.startswith(t) for t in _TOOL_CAPABLE)


class OllamaService(OpenAICompatibleProvider):
    """Ollama local LLM provider.

    Uses Ollama's OpenAI-compatible ``/v1/chat/completions`` for inference
    and the native ``/api/tags`` + ``/api/pull`` endpoints for model
    management.

    Parameters
    ----------
    model:
        Local model name, e.g. ``"llama3.2"`` or ``"qwen2.5:7b"``.
    host:
        Ollama server base URL (default: ``http://localhost:11434``).
    """

    provider_name = "ollama"

    def __init__(
        self,
        model: str = "qwen3:4b",
        host: str = "http://localhost:11434",
        num_ctx: int | None = None,
        **kwargs: Any,
    ) -> None:
        self._host = host.rstrip("/")
        # Ollama's OpenAI-compatible /v1 endpoint silently IGNORES the context
        # window — it always loads the model at its 4096 default, which truncates
        # the large system prompts and context files MARS workflows send. The
        # native /api/chat endpoint honours options.num_ctx, so ``complete`` below
        # uses it. Env-tunable; default sized for long-context workflow prompts.
        self._num_ctx = num_ctx if num_ctx is not None else env_int("MARS_OLLAMA_NUM_CTX", 16384)
        super().__init__(
            model=model,
            api_key="ollama",  # Ollama ignores the key but openai SDK requires one
            base_url=f"{self._host}/v1",
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Inference — native /api/chat (honours num_ctx, unlike /v1)
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        call_kwargs: dict[str, Any] = {**self._default_params, **kwargs}

        # Model options: num_ctx is the whole point of using the native endpoint.
        options: dict[str, Any] = {"num_ctx": self._num_ctx}
        options.update(call_kwargs.pop("options", {}) or {})
        if "temperature" in call_kwargs:
            options["temperature"] = call_kwargs.pop("temperature")
        if "max_tokens" in call_kwargs:  # OpenAI name → Ollama's num_predict
            options["num_predict"] = call_kwargs.pop("max_tokens")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [self._to_ollama_message(m) for m in messages],
            "stream": False,
            "options": options,
        }
        if tools:
            payload["tools"] = [self._tool_schema(t) for t in tools]

        logger.debug("OllamaService.complete model=%s msgs=%d tools=%d num_ctx=%d",
                     self._model, len(messages), len(tools) if tools else 0, self._num_ctx)

        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            resp = await client.post(f"{self._host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return self._parse_ollama_response(data)

    @staticmethod
    def _to_ollama_message(m: LLMMessage) -> dict[str, Any]:
        """Serialise an LLMMessage into Ollama native /api/chat format.

        Differs from the OpenAI shape: a tool result carries ``tool_name`` (not
        ``tool_call_id``), and an assistant's tool-call ``arguments`` is an object
        (the OpenAI wire format stores it as a JSON string)."""
        if m.role == "tool":
            return {"role": "tool", "content": m.content or "", "tool_name": m.name or ""}
        if m.tool_calls:
            calls = []
            for tc in m.tool_calls:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                calls.append({"function": {"name": fn.get("name", ""), "arguments": args}})
            return {"role": "assistant", "content": m.content or "", "tool_calls": calls}
        return {"role": m.role, "content": m.content or ""}

    @staticmethod
    def _parse_ollama_response(data: dict[str, Any]) -> LLMResponse:
        """Parse a native /api/chat response into the OpenAI-shaped LLMResponse
        the wire agent expects (tool-call arguments re-encoded as a JSON string)."""
        msg = data.get("message", {}) or {}
        tool_calls: list[dict[str, Any]] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            tool_calls.append({
                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": args if isinstance(args, str) else json.dumps(args),
                },
            })
        return LLMResponse(
            content=msg.get("content") or None,
            tool_calls=tool_calls,
            finish_reason=data.get("done_reason") or "stop",
            raw=data,
        )

    # ------------------------------------------------------------------
    # Model management – native Ollama API
    # ------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        """Return locally installed Ollama models via ``GET /api/tags``.

        Falls back to an empty list if Ollama is not running.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama list_models failed: %s", exc)
            return []

        models: list[ModelInfo] = []
        for m in data.get("models", []):
            name = m.get("name", "")
            size_bytes = m.get("size", 0)
            size_gb = size_bytes / 1_073_741_824
            models.append(
                ModelInfo(
                    id=name,
                    name=name,
                    description=f"{size_gb:.1f} GB — local Ollama model",
                    context_window=m.get("details", {}).get("context_length", 0),
                    supports_tools=_supports_tools(name),
                    is_free=True,
                )
            )
        return models

    async def pull_model(self, model: str) -> bool:
        """Pull a model from the Ollama registry (``POST /api/pull``).

        Returns ``True`` on success, ``False`` on failure.
        """
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{self._host}/api/pull",
                    json={"name": model, "stream": False},
                )
                resp.raise_for_status()
            logger.info("Ollama: pulled model '%s'", model)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama pull_model('%s') failed: %s", model, exc)
            return False

    async def running_models(self) -> list[str]:
        """Return names of models currently loaded in memory (``GET /api/ps``)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/ps")
                resp.raise_for_status()
                data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama running_models failed: %s", exc)
            return []
