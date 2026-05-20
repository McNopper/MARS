"""System tests for the git service agent via TCP round-trip.

Verifies that the git agent (cost=free) auto-spawns when the server starts,
registers git skills, and that the basic git_operation tool works correctly
in the MARS MCP tool-call chain.
"""
from __future__ import annotations

import pytest
import tests.system.helpers as helpers

from mars.runtime.agents.git_agent import _dispatch as git_dispatch


class TestGitAgentUnit:
    """Fast non-server git agent tests."""

    def test_status_produces_output(self) -> None:
        """Running status against the current repo (which has .git) should succeed."""
        import shutil
        if not shutil.which("git"):
            pytest.skip("git not in PATH")
        result = git_dispatch("status")
        assert isinstance(result, dict)
        assert "ok" in result

    def test_log_three(self) -> None:
        import shutil
        if not shutil.which("git"):
            pytest.skip("git not in PATH")
        result = git_dispatch("log -3")
        assert isinstance(result, dict)
        assert "output" in result

    def test_diff_does_not_crash(self) -> None:
        import shutil
        if not shutil.which("git"):
            pytest.skip("git not in PATH")
        result = git_dispatch("diff")
        assert isinstance(result, dict)


class TestGitAgentServer:
    async def test_git_agent_is_auto_spawned(self, unused_tcp_port: int) -> None:
        """Git agent (cost=free) should appear in the initial roster when scripts are on PATH."""
        if not helpers.builtin_agent_available("mars-agent-git"):
            pytest.skip("mars-agent-git module not found")

        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        spawned = [e for e in initial_events if e.get("t") == "spawn"]
        git_spawns = [
            e for e in spawned
            if any(
                s in (e.get("skills") or [])
                for s in ("git_diff", "git_status", "git", "diff", "vcs")
            )
        ]
        assert git_spawns, (
            "Expected at least one spawn event with a git skill. "
            f"Got: {[e.get('agent_id') for e in spawned]}"
        )

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_git_status_skill_present(self, unused_tcp_port: int) -> None:
        """The git agent should advertise git_status in its skills list."""
        if not helpers.builtin_agent_available("mars-agent-git"):
            pytest.skip("mars-agent-git module not found")

        server = await helpers.start_server(unused_tcp_port)
        await server.start_mcp_agents()

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial_events = await helpers.read_initial_events(h_reader)

        all_skills: list[str] = []
        for e in initial_events:
            if e.get("t") == "spawn":
                all_skills.extend(e.get("skills") or [])

        assert "git_status" in all_skills or "diff" in all_skills, (
            f"git_status or diff skill not found. All skills: {all_skills}"
        )

        h_writer.close()
        await server.stop_mcp_agents()
