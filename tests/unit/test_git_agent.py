"""Unit tests for the git service agent."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mars.runtime.agents.git_agent import _dispatch, _run_git


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal initialised git repository in *tmp_path*."""
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# Test", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"],
                   cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


@pytest.fixture(autouse=True)
def _skip_if_no_gitpython() -> None:
    pytest.importorskip("git", reason="gitpython not installed")


class TestRunGit:
    def test_status_in_repo(self, git_repo: Path) -> None:
        result = _run_git("status", [], cwd=str(git_repo))
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert result["output"]

    def test_diff_empty(self, git_repo: Path) -> None:
        result = _run_git("diff", [], cwd=str(git_repo))
        assert result["ok"] is True

    def test_log_has_commits(self, git_repo: Path) -> None:
        result = _run_git("log", ["-3", "--oneline"], cwd=str(git_repo))
        assert result["ok"] is True
        assert "init" in result["output"]

    def test_not_a_git_repo(self, tmp_path: Path) -> None:
        """Running in a non-repo dir returns ok=False with a clear error."""
        result = _run_git("status", [], cwd=str(tmp_path))
        assert result["ok"] is False
        assert "git repository" in result["error"]

    def test_gitpython_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mars.runtime.agents.git_agent as ga
        monkeypatch.setattr(ga, "_GIT_AVAILABLE", False)
        result = _run_git("status", [])
        assert result["ok"] is False
        assert "gitpython" in result["error"]


class TestDispatch:
    def test_status_plain(self, git_repo: Path) -> None:
        import os
        old = os.getcwd()
        os.chdir(git_repo)
        try:
            result = _dispatch("status")
            assert result["ok"] is True
        finally:
            os.chdir(old)

    def test_git_status_prefix(self, git_repo: Path) -> None:
        import os
        old = os.getcwd()
        os.chdir(git_repo)
        try:
            result = _dispatch("git status")
            assert result["ok"] is True
        finally:
            os.chdir(old)

    def test_log_with_count(self, git_repo: Path) -> None:
        import os
        old = os.getcwd()
        os.chdir(git_repo)
        try:
            result = _dispatch("log -5")
            assert result["ok"] is True
        finally:
            os.chdir(old)

    def test_json_form(self, git_repo: Path) -> None:
        result = _dispatch(
            json.dumps({"op": "log", "args": ["-3", "--oneline"], "cwd": str(git_repo)})
        )
        assert result["ok"] is True
        assert "init" in result["output"]

    def test_json_missing_op(self) -> None:
        result = _dispatch(json.dumps({"args": []}))
        assert result["ok"] is False
        assert "op" in result["error"]

    def test_unknown_op(self) -> None:
        result = _dispatch("frobnicate repo")
        assert result["ok"] is False
        assert "unsupported" in result["error"]

    def test_default_log_args(self, git_repo: Path) -> None:
        """'log' with no extra args should default to -10 --oneline."""
        import os
        old = os.getcwd()
        os.chdir(git_repo)
        try:
            result = _dispatch("log")
            assert result["ok"] is True
            assert "init" in result["output"]
        finally:
            os.chdir(old)

    def test_diff_staged(self, git_repo: Path) -> None:
        """diff --staged should work without error."""
        result = _dispatch(json.dumps({"op": "diff", "args": ["--staged"], "cwd": str(git_repo)}))
        assert result["ok"] is True
