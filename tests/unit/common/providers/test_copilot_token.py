"""Unit tests for Copilot token resolution (env-var support)."""
from __future__ import annotations

import pytest

import mars.server.services.llm.copilot as copilot
from mars.server.services.llm.copilot import _COPILOT_TOKEN_ENV_VARS, _get_token


@pytest.fixture(autouse=True)
def _clear_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _COPILOT_TOKEN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Make the gh fallback deterministic (absent) unless a test opts in.
    monkeypatch.setattr(copilot.shutil, "which", lambda _name: None)


def test_explicit_api_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPILOT_API_KEY", "from-env")
    assert _get_token("explicit") == "explicit"


def test_dedicated_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPILOT_API_KEY", "gho_dedicated")
    assert _get_token() == "gho_dedicated"


def test_github_pat_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    # A classic PAT must NOT authenticate Copilot (the Chat endpoint rejects
    # PATs), so GITHUB_PERSONAL_ACCESS_TOKEN is intentionally not consulted.
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_pat")
    assert _get_token() is None


def test_env_var_priority_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN", "gho_low")
    monkeypatch.setenv("COPILOT_API_KEY", "gho_high")
    assert _get_token() == "gho_high"


def test_whitespace_only_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COPILOT_API_KEY", "   ")
    assert _get_token() is None


def test_none_when_nothing_available() -> None:
    assert _get_token() is None
