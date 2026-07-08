"""Unit tests for mars.server.services.llm.copilot.

Covers:
- _get_token: returns api_key directly, falls back to gh auth token
- CopilotService: raises when no token, passes correct headers
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from mars.server.services.llm.copilot import _get_token


# ---------------------------------------------------------------------------
# _get_token
# ---------------------------------------------------------------------------

class TestGetToken:
    def test_returns_explicit_api_key(self) -> None:
        assert _get_token("gho_explicit") == "gho_explicit"

    def test_calls_gh_auth_token_when_no_key(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(stdout="gho_from_gh\n", returncode=0)
            token = _get_token()
        assert token == "gho_from_gh"

    def test_returns_none_when_gh_not_installed(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            assert _get_token() is None

    def test_returns_none_when_gh_auth_token_empty(self) -> None:
        with mock.patch("shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(stdout="", returncode=0)
            assert _get_token() is None

    def test_calls_gh_auth_token_without_github_token_env(self) -> None:
        """GITHUB_TOKEN must not be passed to gh auth token subprocess.

        If GITHUB_TOKEN is set (e.g. by the Copilot CLI) to a PAT, gh CLI would
        return that PAT instead of the OAuth token stored by gh auth login.
        We must strip it from the subprocess environment.
        """
        captured_env: dict = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return mock.Mock(stdout="gho_from_gh\n", returncode=0)

        with mock.patch("shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("subprocess.run", side_effect=fake_run), \
             mock.patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_fake_pat"}):
            token = _get_token()

        assert token == "gho_from_gh"
        assert "GITHUB_TOKEN" not in captured_env, \
            "GITHUB_TOKEN must be excluded from the gh subprocess environment"


# ---------------------------------------------------------------------------
# CopilotService construction
# ---------------------------------------------------------------------------

class TestCopilotServiceConstruction:
    def test_raises_when_no_token(self) -> None:
        with mock.patch("mars.server.services.llm.copilot._get_token", return_value=None), \
             mock.patch("openai.AsyncOpenAI"):
            from mars.server.services.llm.copilot import CopilotService
            with pytest.raises(ValueError, match="gh auth login"):
                CopilotService()

    def test_constructs_with_explicit_api_key(self) -> None:
        with mock.patch("openai.AsyncOpenAI"):
            from mars.server.services.llm.copilot import CopilotService
            p = CopilotService(api_key="gho_explicit", model="gpt-4o-mini")
        assert p.model == "gpt-4o-mini"

    def test_constructs_via_gh_auth_token(self) -> None:
        with mock.patch("mars.server.services.llm.copilot._get_token", return_value="gho_from_gh"), \
             mock.patch("openai.AsyncOpenAI"):
            from mars.server.services.llm.copilot import CopilotService
            p = CopilotService()
        assert p.model == "gpt-4o"

    def test_vscode_headers_present(self) -> None:
        """Provider must send VS Code headers so GitHub recognises the request."""
        with mock.patch("mars.server.services.llm._openai_compat.AsyncOpenAI") as mock_oai:
            from mars.server.services.llm.copilot import CopilotService
            CopilotService(api_key="gho_tok")
        _, kwargs = mock_oai.call_args
        headers = kwargs.get("default_headers", {})
        assert headers.get("Copilot-Integration-Id") == "vscode-chat"
        assert "vscode" in headers.get("Editor-Version", "")

