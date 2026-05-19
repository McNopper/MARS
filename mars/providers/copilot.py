"""GitHub Copilot LLM provider for MARS.

Uses the GitHub Copilot Chat API, which is OpenAI-compatible.
Requires a GitHub personal access token with Copilot access.

Docs:    https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-command-line
API:     https://api.githubcopilot.com
Install: pip install openai   (already a MARS dependency)

Authentication (in order of priority)
--------------------------------------
1. ``api_key`` argument passed directly
2. ``GITHUB_TOKEN`` environment variable
3. ``GH_TOKEN`` environment variable
4. Token from ``gh auth token`` (GitHub CLI, if installed)

Available models
----------------
    gpt-4o                  – GPT-4o (default, fast + capable)
    gpt-4o-mini             – GPT-4o mini (faster, lighter)
    o1-mini                 – OpenAI o1-mini (reasoning)
    claude-3.5-sonnet       – Anthropic Claude 3.5 Sonnet
    claude-3.7-sonnet       – Anthropic Claude 3.7 Sonnet

Example
-------
    # Set token in .env:
    #   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    from mars.providers.copilot import CopilotProvider
    provider = CopilotProvider()               # picks up GITHUB_TOKEN
    provider = CopilotProvider(model="claude-3.5-sonnet")
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from mars.providers._openai_compat import OpenAICompatibleProvider

_COPILOT_API = "https://api.githubcopilot.com"


def _resolve_token(api_key: str | None) -> str | None:
    """Try every source for a GitHub token."""
    if api_key:
        return api_key
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_COPILOT_TOKEN"):
        val = os.environ.get(var)
        if val:
            return val
    # Last resort: ask gh CLI
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


class CopilotProvider(OpenAICompatibleProvider):
    """GitHub Copilot Chat API provider.

    Parameters
    ----------
    model:
        Copilot model identifier. Defaults to ``gpt-4o``.
    api_key:
        GitHub personal access token. If omitted, falls back to the
        ``GITHUB_TOKEN`` / ``GH_TOKEN`` environment variables, then
        ``gh auth token``.
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
                "GitHub Copilot provider requires a token.\n"
                "Set GITHUB_TOKEN in your environment or .env file,\n"
                "or install the GitHub CLI and run: gh auth login"
            )
        super().__init__(
            model=model,
            api_key=token,
            base_url=_COPILOT_API,
            extra_headers={
                "Editor-Version":         "mars/1.0",
                "Editor-Plugin-Version":  "mars-agent/1.0",
                "Copilot-Integration-Id": "mars-agent",
            },
            **kwargs,
        )

    async def list_models(self) -> list[Any]:
        from mars.providers.base import ModelInfo
        return [
            ModelInfo("gpt-4o",             "GPT-4o",              "Fast, capable", 128_000, is_free=True),
            ModelInfo("gpt-4o-mini",        "GPT-4o mini",         "Faster, lighter", 128_000, is_free=True),
            ModelInfo("o1-mini",            "o1-mini",             "Reasoning", 65_536, is_free=True),
            ModelInfo("claude-3.5-sonnet",  "Claude 3.5 Sonnet",  "Anthropic, high quality", 200_000, is_free=True),
            ModelInfo("claude-3.7-sonnet",  "Claude 3.7 Sonnet",  "Anthropic, latest", 200_000, is_free=True),
        ]
