"""z.AI LLM provider for MARS.

z.AI (ZhipuAI) serves the GLM model family via an OpenAI-compatible REST API.

Docs:   https://docs.z.ai/api-reference/introduction
Models: https://docs.z.ai/api-reference/chat-completions

Token resolution order:
  1. explicit ``api_key="..."`` argument,
  2. ``ZAI_API_KEY`` environment variable,
  3. ``ZHIPUAI_API_KEY`` environment variable (alternative name).

Get an API key at https://platform.z.ai/ (register → API Keys).

Base URL: https://api.z.ai/api/paas/v4/

Recommended models
------------------
  glm-4-flash       – Fast, free tier (limited rate)
  glm-4-air         – Balanced cost / quality
  glm-4             – High quality, paid
  glm-4-plus        – Highest quality
  glm-z1-flash      – Reasoning model, fast
  glm-z1-air        – Reasoning model, balanced
"""

from __future__ import annotations

import logging
import os
from typing import Any

from mars.server.services.llm._openai_compat import OpenAICompatibleProvider
from mars.server.services.llm.base import ModelInfo

logger = logging.getLogger(__name__)

_ZAI_API = "https://api.z.ai/api/paas/v4/"

_ZAI_TOKEN_ENV_VARS = ("ZAI_API_KEY", "ZHIPUAI_API_KEY")


def _get_token(api_key: str | None = None) -> str | None:
    """Return the z.AI API key.

    Resolution: explicit ``api_key`` → ``ZAI_API_KEY`` → ``ZHIPUAI_API_KEY``.
    """
    if api_key:
        return api_key
    for var in _ZAI_TOKEN_ENV_VARS:
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
    return None


class ZAIService(OpenAICompatibleProvider):
    """z.AI (ZhipuAI) GLM model provider.

    Uses the OpenAI-compatible ``/api/paas/v4/chat/completions`` endpoint.

    Parameters
    ----------
    model:
        GLM model identifier.  Defaults to ``glm-4-flash`` (free tier).
    api_key:
        z.AI API key.  Falls back to ``ZAI_API_KEY`` / ``ZHIPUAI_API_KEY`` env vars.
    """

    provider_name = "zai"

    KNOWN_MODELS: dict[str, ModelInfo] = {m.id: m for m in [
        # Current flagship
        ModelInfo("glm-5.2",       "GLM-5.2",       "Current flagship model",        128_000, supports_tools=True,  is_free=False),
        # Free-tier / high-speed models
        ModelInfo("glm-4-flash",   "GLM-4 Flash",   "Fast, free tier",               128_000, supports_tools=True,  is_free=True),
        ModelInfo("glm-4-flash-250414", "GLM-4 Flash (Apr 2025)", "Latest flash",    128_000, supports_tools=True,  is_free=True),
        ModelInfo("glm-z1-flash",  "GLM-Z1 Flash",  "Reasoning model, fast, free",   128_000, supports_tools=False, is_free=True),
        # Balanced paid models
        ModelInfo("glm-4-air",     "GLM-4 Air",     "Balanced cost/quality",         128_000, supports_tools=True,  is_free=False),
        ModelInfo("glm-4-airx",    "GLM-4 AirX",    "Higher speed variant",          128_000, supports_tools=True,  is_free=False),
        ModelInfo("glm-z1-air",    "GLM-Z1 Air",    "Reasoning model, balanced",     128_000, supports_tools=False, is_free=False),
        # High-quality paid models
        ModelInfo("glm-4",         "GLM-4",         "High quality",                  128_000, supports_tools=True,  is_free=False),
        ModelInfo("glm-4-plus",    "GLM-4 Plus",    "Highest quality",               128_000, supports_tools=True,  is_free=False),
        ModelInfo("glm-4-long",    "GLM-4 Long",    "Extended 1M context window",  1_000_000, supports_tools=True,  is_free=False),
        ModelInfo("glm-z1",        "GLM-Z1",        "Reasoning model, high quality", 128_000, supports_tools=False, is_free=False),
    ]}

    def __init__(
        self,
        model: str = "glm-5.2",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        token = _get_token(api_key)
        if not token:
            raise ValueError(
                "z.AI: no API key found. Set ZAI_API_KEY or pass api_key=."
            )
        super().__init__(
            model=model,
            api_key=token,
            base_url=_ZAI_API,
            **kwargs,
        )

    async def list_models(self) -> list[ModelInfo]:
        """Return available z.AI models.

        Attempts the live ``/models`` endpoint; falls back to the curated
        :attr:`KNOWN_MODELS` catalogue on failure.
        """
        try:
            resp = await self._client.models.list()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ZAIService list_models failed (%s); using curated catalogue", exc)
            return list(self.KNOWN_MODELS.values())

        models: list[ModelInfo] = []
        for m in getattr(resp, "data", []) or []:
            mid = getattr(m, "id", None)
            if not mid:
                continue
            models.append(
                self.KNOWN_MODELS.get(mid)
                or ModelInfo(
                    id=mid,
                    name=mid,
                    description="z.AI model",
                    supports_tools=mid.startswith("glm-4"),
                )
            )
        return models or list(self.KNOWN_MODELS.values())
