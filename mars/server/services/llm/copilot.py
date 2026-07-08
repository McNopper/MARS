"""GitHub Copilot LLM provider for MARS.

Token resolution order:
  1. an explicit ``api_key="gho_..."`` argument,
  2. a dedicated env var — ``COPILOT_API_KEY`` / ``GH_COPILOT_TOKEN`` /
     ``GITHUB_COPILOT_TOKEN`` (set one in ``.env`` to a Copilot OAuth token),
  3. ``gh auth token`` (run ``gh auth login`` once).

Note: the Copilot Chat endpoint rejects classic *Personal Access Tokens*
("Personal Access Tokens are not supported for this endpoint"), so a
``GITHUB_PERSONAL_ACCESS_TOKEN`` PAT cannot authenticate Copilot — use a
Copilot OAuth token (``gho_…``) or ``gh auth login`` instead.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

from mars.server.services.llm._openai_compat import OpenAICompatibleProvider
from mars.server.services.llm.base import ModelInfo

logger = logging.getLogger(__name__)

_COPILOT_API = "https://api.githubcopilot.com"

# Dedicated Copilot token env vars, checked in order — set one in .env to a
# Copilot OAuth token (gho_…).  ``GITHUB_PERSONAL_ACCESS_TOKEN`` / ``GITHUB_TOKEN``
# are deliberately excluded: the Copilot Chat endpoint rejects classic PATs, and
# a generic PAT must not shadow a real Copilot token (GITHUB_TOKEN is also
# stripped from the gh subprocess env below).
_COPILOT_TOKEN_ENV_VARS = (
    "COPILOT_API_KEY",
    "GH_COPILOT_TOKEN",
    "GITHUB_COPILOT_TOKEN",
)


def _get_token(api_key: str | None = None) -> str | None:
    """Return the GitHub OAuth token for the Copilot API.

    Resolution order: explicit ``api_key`` → a dedicated Copilot env var
    (:data:`_COPILOT_TOKEN_ENV_VARS`) → ``gh auth token``.

    ``GITHUB_TOKEN`` is removed from the subprocess environment so that
    any PAT set by external tools (e.g. the Copilot CLI) does not shadow
    the OAuth token stored by ``gh auth login``.
    """
    if api_key:
        return api_key
    for var in _COPILOT_TOKEN_ENV_VARS:
        val = os.environ.get(var)
        if val and val.strip():
            return val.strip()
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


class CopilotService(OpenAICompatibleProvider):
    """GitHub Copilot Chat API provider.

    Parameters
    ----------
    model:
        Copilot model identifier.  Defaults to ``gpt-4o``.
    api_key:
        GitHub OAuth token (``gho_…``).  Falls back to ``gh auth token``.
    """

    provider_name = "copilot"
    # GitHub Copilot bills "premium request" models (Claude, Gemini Pro, GPT-5,
    # o-series, …) against a limited/paid quota — they are NOT free.  Only the
    # included base GPT-4o / GPT-4.1 / GPT-3.5 family runs at no extra cost.
    # ``is_free`` must reflect that so the cost view and tier picking are honest.
    KNOWN_MODELS: dict[str, ModelInfo] = {m.id: m for m in [
        # Included in the Copilot subscription (no premium-request cost):
        ModelInfo("gpt-4o",             "GPT-4o",             "Fast, capable (included)",   128_000, is_free=True),
        ModelInfo("gpt-4o-mini",        "GPT-4o mini",        "Faster, lighter (included)", 128_000, is_free=True),
        ModelInfo("gpt-4.1",            "GPT-4.1",            "Capable (included)",         128_000, is_free=True),
        # Premium-request models (consume Copilot's limited premium quota):
        ModelInfo("claude-sonnet-4.5",  "Claude Sonnet 4.5",  "Anthropic (premium)", 200_000, is_free=False, pricing_notes="Copilot premium request"),
        ModelInfo("claude-sonnet-4.6",  "Claude Sonnet 4.6",  "Anthropic (premium)", 200_000, is_free=False, pricing_notes="Copilot premium request"),
        ModelInfo("claude-haiku-4.5",   "Claude Haiku 4.5",   "Anthropic (premium)", 200_000, is_free=False, pricing_notes="Copilot premium request"),
        ModelInfo("claude-opus-4.5",    "Claude Opus 4.5",    "Anthropic (premium)", 200_000, is_free=False, pricing_notes="Copilot premium request"),
        ModelInfo("claude-opus-4.8",    "Claude Opus 4.8",    "Anthropic (premium)", 200_000, is_free=False, pricing_notes="Copilot premium request"),
        ModelInfo("gemini-2.5-pro",     "Gemini 2.5 Pro",     "Google (premium)",   1_000_000, is_free=False, pricing_notes="Copilot premium request"),
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
        """Return every Copilot-available model from the live ``/models`` endpoint.

        Known models are enriched with curated metadata; unknown ones are still
        returned so any model the account can access is usable.  Falls back to
        the curated :attr:`KNOWN_MODELS` catalogue if the request fails.
        """
        try:
            resp = await self._client.models.list()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Copilot list_models failed (%s); using curated catalogue", exc)
            return list(self.KNOWN_MODELS.values())

        models: list[ModelInfo] = []
        for m in getattr(resp, "data", []) or []:
            mid = getattr(m, "id", None)
            if not mid:
                continue
            # Unknown models default to NOT free: Copilot keeps adding premium
            # (premium-request) models, so claiming a model is free by default
            # under-reports cost.  The included base family is matched explicitly.
            models.append(
                self.KNOWN_MODELS.get(mid)
                or ModelInfo(
                    id=mid, name=mid, description="GitHub Copilot model",
                    is_free=self._is_included_model(mid),
                )
            )
        return models or list(self.KNOWN_MODELS.values())

    # GitHub Copilot includes the base GPT-4o / GPT-4.1 / GPT-3.5 (and legacy
    # gpt-4) families at no premium-request cost.  Everything else — Claude,
    # Gemini Pro, GPT-5.x, o-series — is a premium-request (paid/limited) model.
    _INCLUDED_PREFIXES = ("gpt-4o", "gpt-4.1", "gpt-3.5", "gpt-4-", "text-embedding")

    @classmethod
    def _is_included_model(cls, model_id: str) -> bool:
        """True if *model_id* runs under the Copilot subscription at no premium cost."""
        mid = model_id.lower()
        if mid in ("gpt-4", "gpt-4o"):
            return True
        return any(mid.startswith(p) for p in cls._INCLUDED_PREFIXES)

