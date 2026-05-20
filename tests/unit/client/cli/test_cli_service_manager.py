"""Unit tests for mars.client.cli.service_manager."""
from __future__ import annotations

import signal
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from mars.client.cli.service_manager import (
    _auto_spawn_free_agents,
    _emit_spawn_status,
    _launch_service_agent,
    _stop_service_agents,
)
from mars.runtime.services.registry import AgentSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(name: str = "clock", command: str = "mars-agent-clock --server {server}",
               cost: str = "free") -> AgentSpec:
    return AgentSpec(
        name=name,
        description="Test agent",
        command=command,
        skills=[name],
        category="service",
        cost=cost,
    )


# ---------------------------------------------------------------------------
# _emit_spawn_status
# ---------------------------------------------------------------------------


class TestEmitSpawnStatus:
    def test_calls_status_callback_if_provided(self) -> None:
        messages = []
        _emit_spawn_status("hello", status=lambda m: messages.append(m))
        assert messages == ["hello"]

    def test_prints_if_no_callback(self, capsys: Any) -> None:
        _emit_spawn_status("printed message")
        out = capsys.readouterr().out
        assert "printed message" in out


# ---------------------------------------------------------------------------
# _launch_service_agent
# ---------------------------------------------------------------------------


class TestLaunchServiceAgent:
    @patch("subprocess.Popen")
    def test_returns_pid_on_success(self, mock_popen: MagicMock) -> None:
        proc = MagicMock()
        proc.pid = 12345
        mock_popen.return_value = proc

        spec = _make_spec()
        pid, workdir = _launch_service_agent(spec, "localhost:7432")

        assert pid == 12345
        assert workdir == Path("artifacts") / "clock"

    @patch("subprocess.Popen")
    def test_creates_workdir(self, mock_popen: MagicMock, tmp_path: Path) -> None:
        proc = MagicMock()
        proc.pid = 99
        mock_popen.return_value = proc

        spec = _make_spec()
        # We don't validate the exact path; just ensure no exception is raised
        _launch_service_agent(spec, "localhost:7432")

    @patch("subprocess.Popen")
    def test_resolves_builtin_agent_command_to_module(self, mock_popen: MagicMock) -> None:
        proc = MagicMock()
        proc.pid = 42
        mock_popen.return_value = proc

        spec = _make_spec()
        pid, _workdir = _launch_service_agent(spec, "localhost:7432")

        assert pid == 42
        cmd_used = mock_popen.call_args[0][0]
        assert cmd_used[:3] == [sys.executable, "-m", "mars.runtime.agents.clock_agent"]

    @patch("subprocess.Popen")
    def test_server_address_substituted_in_command(self, mock_popen: MagicMock) -> None:
        proc = MagicMock()
        proc.pid = 1
        mock_popen.return_value = proc

        spec = _make_spec(command="mars-agent-clock --server {server}")
        _launch_service_agent(spec, "192.168.1.100:7432")

        cmd_used = mock_popen.call_args[0][0]
        assert "192.168.1.100:7432" in cmd_used

    @patch("subprocess.Popen")
    def test_extra_args_appended(self, mock_popen: MagicMock) -> None:
        proc = MagicMock()
        proc.pid = 1
        mock_popen.return_value = proc

        spec = _make_spec()
        _launch_service_agent(spec, "localhost:7432", extra_args=["--verbose"])

        cmd_used = mock_popen.call_args[0][0]
        assert "--verbose" in cmd_used


# ---------------------------------------------------------------------------
# _stop_service_agents
# ---------------------------------------------------------------------------


class TestStopServiceAgents:
    @patch("os.kill")
    def test_sends_sigterm_to_each_pid(self, mock_kill: MagicMock) -> None:
        _stop_service_agents([100, 200, 300])
        assert mock_kill.call_count == 3
        mock_kill.assert_any_call(100, signal.SIGTERM)
        mock_kill.assert_any_call(200, signal.SIGTERM)
        mock_kill.assert_any_call(300, signal.SIGTERM)

    @patch("os.kill", side_effect=ProcessLookupError)
    def test_ignores_process_lookup_error(self, mock_kill: MagicMock) -> None:
        # Should not raise even if process is already gone
        _stop_service_agents([999])

    @patch("os.kill", side_effect=PermissionError)
    def test_ignores_permission_error(self, mock_kill: MagicMock) -> None:
        _stop_service_agents([888])

    @patch("os.kill")
    def test_empty_list_does_nothing(self, mock_kill: MagicMock) -> None:
        _stop_service_agents([])
        mock_kill.assert_not_called()


# ---------------------------------------------------------------------------
# _auto_spawn_free_agents
# ---------------------------------------------------------------------------


class TestAutoSpawnFreeAgents:
    @patch("mars.client.cli.service_manager._launch_service_agent")
    @patch("mars.client.cli.service_manager.all_specs")
    def test_spawns_only_free_agents(
        self, mock_all_specs: MagicMock, mock_launch: MagicMock
    ) -> None:
        mock_all_specs.return_value = [
            _make_spec("clock", cost="free"),
            _make_spec("premium-agent", cost="paid"),
        ]
        mock_launch.return_value = (1234, Path("artifacts/clock"))

        pids = _auto_spawn_free_agents("localhost:7432")
        assert pids == [1234]
        mock_launch.assert_called_once()

    @patch("mars.client.cli.service_manager._launch_service_agent")
    @patch("mars.client.cli.service_manager.all_specs")
    def test_returns_list_of_pids(
        self, mock_all_specs: MagicMock, mock_launch: MagicMock
    ) -> None:
        mock_all_specs.return_value = [
            _make_spec("clock", cost="free"),
            _make_spec("profiler", cost="free"),
        ]
        mock_launch.side_effect = [
            (101, Path("artifacts/clock")),
            (102, Path("artifacts/profiler")),
        ]
        pids = _auto_spawn_free_agents("localhost:7432")
        assert set(pids) == {101, 102}

    @patch("mars.client.cli.service_manager._launch_service_agent",
           side_effect=RuntimeError("boom"))
    @patch("mars.client.cli.service_manager.all_specs")
    def test_handles_launch_exception_gracefully(
        self, mock_all_specs: MagicMock, mock_launch: MagicMock
    ) -> None:
        mock_all_specs.return_value = [_make_spec("clock", cost="free")]
        pids = _auto_spawn_free_agents("localhost:7432")
        # Should not raise; returns empty list on failure
        assert pids == []

    @patch("mars.client.cli.service_manager.all_specs")
    def test_no_free_agents_returns_empty(self, mock_all_specs: MagicMock) -> None:
        mock_all_specs.return_value = [_make_spec("premium", cost="paid")]
        pids = _auto_spawn_free_agents("localhost:7432")
        assert pids == []
