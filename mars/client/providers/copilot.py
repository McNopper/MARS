"""GitHub Copilot LLM provider for MARS.

Uses the GitHub Copilot Chat API (``api.githubcopilot.com``), which is
OpenAI-compatible.

Authentication
--------------
The provider uses the GitHub OAuth token produced by ``gh auth login``
(the ``gho_…`` token).  No token exchange or additional setup is required.

**One-time setup**::

    gh auth login

After that, ``CopilotProvider`` resolves the token automatically via
``gh auth token``.  You can also pass the token explicitly::

    provider = CopilotProvider(api_key="gho_...")

Available models
----------------
    gpt-4o                  – GPT-4o (default, fast + capable)
    gpt-4o-mini             – GPT-4o mini (faster, lighter)
    o1-mini                 – OpenAI o1-mini (reasoning)
    claude-3.5-sonnet       – Anthropic Claude 3.5 Sonnet
    claude-3.7-sonnet       – Anthropic Claude 3.7 Sonnet

Example
-------
    from mars.client.providers.copilot import CopilotProvider
    provider = CopilotProvider()
    provider = CopilotProvider(model="gpt-4o-mini")
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from mars.client.providers._openai_compat import OpenAICompatibleProvider
from mars.client.providers.base import LLMMessage, LLMResponse, ToolSpec

_COPILOT_API = "https://api.githubcopilot.com"


def _gh_auth_token() -> str | None:
    """Return the token from ``gh auth token``, stripping env overrides."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5, env=env,
        )
        token = result.stdout.strip()
        return token if token else None
    except Exception:
        return None


def _resolve_token(api_key: str | None) -> str | None:
    """Return a GitHub OAuth token suitable for the Copilot Chat API.

    Sources (in priority order)
    ---------------------------
    1. ``api_key`` argument — passed explicitly by the caller.
    2. ``gh auth token`` — called automatically if ``gh`` is on PATH.
    """
    if api_key:
        return api_key
    return _gh_auth_token()


class CopilotProvider(OpenAICompatibleProvider):
    """GitHub Copilot Chat API provider.

    Parameters
    ----------
    model:
        Copilot model identifier.  Defaults to ``gpt-4o``.
    api_key:
        GitHub OAuth token (``gho_…``).  Falls back to ``gh auth token``
        automatically.
    """

    provider_name = "copilot"

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        token = _resolve_token(api_key)
        if not token:
            raise ValueError(
                "GitHub Copilot provider: no token found.\n"
                "Run 'gh auth login' (and ensure gh is on PATH) to authenticate."
            )
        super().__init__(
            model=model,
            api_key=token,
            base_url=_COPILOT_API,
            extra_headers={
                "Editor-Version":         "vscode/1.85.0",
                "Editor-Plugin-Version":  "mars-agent/1.0",
                "Copilot-Integration-Id": "vscode-chat",
            },
            **kwargs,
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await super().complete(messages, tools, **kwargs)

    async def list_models(self) -> list[Any]:
        from mars.client.providers.base import ModelInfo
        return [
            ModelInfo("gpt-4o",             "GPT-4o",              "Fast, capable",          128_000, is_free=True),
            ModelInfo("gpt-4o-mini",        "GPT-4o mini",         "Faster, lighter",         128_000, is_free=True),
            ModelInfo("o1-mini",            "o1-mini",             "Reasoning",                65_536, is_free=True),
            ModelInfo("claude-3.5-sonnet",  "Claude 3.5 Sonnet",  "Anthropic, high quality", 200_000, is_free=True),
            ModelInfo("claude-3.7-sonnet",  "Claude 3.7 Sonnet",  "Anthropic, latest",       200_000, is_free=True),
        ]

