"""GitHub Copilot LLM provider for MARS.

Authenticates via ``gh auth login`` — run that once and the token is resolved
automatically.  Pass ``api_key="gho_..."`` to override.
"""

from __future__ import annotations

from typing import Any

from mars.client.providers._openai_compat import OpenAICompatibleProvider
from mars.client.providers.base import ModelInfo

_COPILOT_API = "https://api.githubcopilot.com"


def _get_token(api_key: str | None = None) -> str | None:
    """Return the GitHub OAuth token for the Copilot API.

    Uses ``api_key`` when provided, otherwise calls ``gh auth token``.

    ``GITHUB_TOKEN`` is removed from the subprocess environment so that
    any PAT set by external tools (e.g. the Copilot CLI) does not shadow
    the OAuth token stored by ``gh auth login``.
    """
    if api_key:
        return api_key
    import os
    import shutil
    import subprocess
    if not shutil.which("gh"):
        return None
    try:
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5,
            env=env,
        )
        token = result.stdout.strip()
        return token if token else None
    except Exception:
        return None


class CopilotProvider(OpenAICompatibleProvider):
    """GitHub Copilot Chat API provider.

    Parameters
    ----------
    model:
        Copilot model identifier.  Defaults to ``gpt-4o``.
    api_key:
        GitHub OAuth token (``gho_…``).  Falls back to ``gh auth token``.
    """

    provider_name = "copilot"
    KNOWN_MODELS: dict[str, ModelInfo] = {m.id: m for m in [
        ModelInfo("gpt-4o",             "GPT-4o",             "Fast, capable",        128_000, is_free=True),
        ModelInfo("gpt-4o-mini",        "GPT-4o mini",        "Faster, lighter",      128_000, is_free=True),
        ModelInfo("o1-mini",            "o1-mini",            "Reasoning",             65_536, is_free=True),
        ModelInfo("claude-3.5-sonnet",  "Claude 3.5 Sonnet",  "Anthropic, capable",   200_000, is_free=True),
        ModelInfo("claude-3.7-sonnet",  "Claude 3.7 Sonnet",  "Anthropic, latest",    200_000, is_free=True),
    ]}

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        token = _get_token(api_key)
        if not token:
            raise ValueError(
                "GitHub Copilot: no token found. Run 'gh auth login'."
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

    async def list_models(self) -> list[ModelInfo]:
        return list(self.KNOWN_MODELS.values())

