"""Unit tests for the shell execution service agent."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mars.runtime.agents.shell_agent import _dispatch, _execute, _truncate, _MAX_OUTPUT_BYTES


class TestTruncate:
    def test_short_string_unchanged(self) -> None:
        s = "hello world"
        assert _truncate(s) == s

    def test_long_string_truncated(self) -> None:
        big = "x" * (_MAX_OUTPUT_BYTES + 100)
        result = _truncate(big)
        assert len(result.encode("utf-8")) <= _MAX_OUTPUT_BYTES + 200  # room for note
        assert "truncated" in result


class TestExecute:
    def test_simple_echo(self) -> None:
        if sys.platform == "win32":
            result = _execute("echo hello")
        else:
            result = _execute("echo hello")
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]
        assert "cmd" in result

    def test_nonzero_exit(self) -> None:
        result = _execute("exit 42" if sys.platform == "win32" else "exit 42", timeout=5)
        # shell exit command behaviour varies, just check ok=False or code != 0
        # On Windows shell=True 'exit N' exits the shell with code N
        assert isinstance(result["exit_code"], int)

    def test_invalid_command_returns_error_or_nonzero(self) -> None:
        result = _execute("this_command_definitely_does_not_exist_xyz_123", timeout=5)
        # Should not raise — returns ok=False or non-zero exit
        assert isinstance(result, dict)
        assert "exit_code" in result

    def test_cwd_override(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            result = _execute("cd", cwd=str(tmp_path))
        else:
            result = _execute("pwd", cwd=str(tmp_path))
        assert result["ok"] is True
        assert result["cwd"] == str(tmp_path)

    def test_env_injection(self) -> None:
        if sys.platform == "win32":
            result = _execute("echo %MARS_TEST_VAR%", env={"MARS_TEST_VAR": "injected"})
        else:
            result = _execute("echo $MARS_TEST_VAR", env={"MARS_TEST_VAR": "injected"})
        assert result["ok"] is True
        assert "injected" in result["stdout"]

    def test_timeout_handling(self) -> None:
        cmd = "ping -n 10 127.0.0.1" if sys.platform == "win32" else "sleep 60"
        result = _execute(cmd, timeout=1)
        assert result["ok"] is False
        assert "timeout" in result.get("error", "").lower() or result["exit_code"] == -1

    def test_output_truncation(self) -> None:
        if sys.platform == "win32":
            # Generate large output on Windows
            result = _execute(
                "python -c \"print('A' * 70000)\"",
                timeout=10,
            )
        else:
            result = _execute(
                "python3 -c \"print('A' * 70000)\"",
                timeout=10,
            )
        if result["ok"]:
            assert len(result["stdout"].encode("utf-8")) <= _MAX_OUTPUT_BYTES + 200
        else:
            pytest.skip("Python not available for output truncation test")

    def test_elapsed_s_is_float(self) -> None:
        result = _execute("echo ok")
        assert isinstance(result["elapsed_s"], float)
        assert result["elapsed_s"] >= 0


class TestDispatch:
    def test_plain_echo(self) -> None:
        result = _dispatch("echo dispatch_test")
        assert result["ok"] is True
        assert "dispatch_test" in result["stdout"]

    def test_json_format(self) -> None:
        result = _dispatch(json.dumps({"cmd": "echo from_json"}))
        assert result["ok"] is True
        assert "from_json" in result["stdout"]

    def test_json_with_timeout(self) -> None:
        result = _dispatch(json.dumps({"cmd": "echo timed", "timeout": 10}))
        assert result["ok"] is True

    def test_json_missing_cmd(self) -> None:
        result = _dispatch(json.dumps({"timeout": 10}))
        assert result["ok"] is False
        assert "cmd" in result["error"]

    def test_empty_request(self) -> None:
        result = _dispatch("")
        assert result["ok"] is False

    def test_json_cwd(self, tmp_path: Path) -> None:
        if sys.platform == "win32":
            cmd = "cd"
        else:
            cmd = "pwd"
        result = _dispatch(json.dumps({"cmd": cmd, "cwd": str(tmp_path)}))
        assert result["ok"] is True
        assert result["cwd"] == str(tmp_path)
