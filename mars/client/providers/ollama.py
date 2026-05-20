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

import logging
from typing import Any

from mars.client.providers._openai_compat import OpenAICompatibleProvider
from mars.client.providers.base import ModelInfo

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


class OllamaProvider(OpenAICompatibleProvider):
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
        model: str = "llama3.2",
        host: str = "http://localhost:11434",
        **kwargs: Any,
    ) -> None:
        self._host = host.rstrip("/")
        super().__init__(
            model=model,
            api_key="ollama",  # Ollama ignores the key but openai SDK requires one
            base_url=f"{self._host}/v1",
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Model management – native Ollama API
    # ------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        """Return locally installed Ollama models via ``GET /api/tags``.

        Falls back to an empty list if Ollama is not running.
        """
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed; cannot list Ollama models")
            return []
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
            import httpx
        except ImportError:
            logger.warning("httpx not installed; cannot pull Ollama models")
            return False
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
            import httpx
        except ImportError:
            return []
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._host}/api/ps")
                resp.raise_for_status()
                data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama running_models failed: %s", exc)
            return []
