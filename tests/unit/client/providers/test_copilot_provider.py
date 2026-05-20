"""Unit tests for mars.client.providers.copilot.

Covers:
- _gh_auth_token: gh CLI not available / strips env overrides
- _resolve_token: priority order (api_key -> gh CLI)
- CopilotProvider.__init__: raises ValueError when no token, uses correct headers
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from mars.client.providers.copilot import _gh_auth_token, _resolve_token


# ---------------------------------------------------------------------------
# _gh_auth_token
# ---------------------------------------------------------------------------

class TestGhAuthToken:
    def test_returns_token_from_stdout(self) -> None:
        result = mock.MagicMock()
        result.stdout = "gho_abc123\n"
        with mock.patch("subprocess.run", return_value=result) as mock_run:
            token = _gh_auth_token()
        assert token == "gho_abc123"
        # GITHUB_TOKEN must be stripped from the env passed to subprocess
        call_env = mock_run.call_args.kwargs["env"]
        assert "GITHUB_TOKEN" not in call_env
        assert "GH_TOKEN"     not in call_env

    def test_returns_none_when_gh_not_found(self) -> None:
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            token = _gh_auth_token()
        assert token is None

    def test_returns_none_on_empty_output(self) -> None:
        result = mock.MagicMock()
        result.stdout = "   \n"
        with mock.patch("subprocess.run", return_value=result):
            token = _gh_auth_token()
        assert token is None


# ---------------------------------------------------------------------------
# _resolve_token
# ---------------------------------------------------------------------------

class TestResolveToken:
    def test_explicit_api_key_wins(self) -> None:
        with mock.patch("subprocess.run") as mock_run:
            token = _resolve_token("gho_explicit")
        assert token == "gho_explicit"
        mock_run.assert_not_called()

    def test_gh_cli_used_when_no_api_key(self) -> None:
        with mock.patch("mars.client.providers.copilot._gh_auth_token",
                        return_value="gho_from_cli"):
            token = _resolve_token(None)
        assert token == "gho_from_cli"

    def test_returns_none_when_nothing_available(self) -> None:
        with mock.patch("mars.client.providers.copilot._gh_auth_token",
                        return_value=None):
            token = _resolve_token(None)
        assert token is None


# ---------------------------------------------------------------------------
# CopilotProvider construction
# ---------------------------------------------------------------------------

class TestCopilotProviderConstruction:
    def test_raises_when_no_token(self) -> None:
        with mock.patch("mars.client.providers.copilot._gh_auth_token",
                        return_value=None):
            with mock.patch("openai.AsyncOpenAI"):
                from mars.client.providers.copilot import CopilotProvider
                with pytest.raises(ValueError, match="GitHub Copilot"):
                    CopilotProvider()

    def test_constructs_with_gh_cli_token(self) -> None:
        with mock.patch("mars.client.providers.copilot._gh_auth_token",
                        return_value="gho_cli_token"):
            with mock.patch("openai.AsyncOpenAI"):
                from mars.client.providers.copilot import CopilotProvider
                p = CopilotProvider()
        assert p.model == "gpt-4o"

    def test_constructs_with_explicit_api_key(self) -> None:
        with mock.patch("openai.AsyncOpenAI"):
            from mars.client.providers.copilot import CopilotProvider
            p = CopilotProvider(api_key="gho_explicit", model="gpt-4o-mini")
        assert p.model == "gpt-4o-mini"

    def test_vscode_headers_present(self) -> None:
        """Provider must send VS Code headers so GitHub recognises the request."""
        with mock.patch("openai.AsyncOpenAI") as mock_oai:
            from mars.client.providers.copilot import CopilotProvider
            CopilotProvider(api_key="gho_tok")
        _, kwargs = mock_oai.call_args
        headers = kwargs.get("default_headers", {})
        assert headers.get("Copilot-Integration-Id") == "vscode-chat"
        assert "vscode" in headers.get("Editor-Version", "")
