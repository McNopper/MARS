"""System tests: server command validation.

Exercises server-side commands (/spawn, /switch, unknown commands) and
message routing via the TCP wire protocol.

No external services required — uses the mock provider and offline helpers.
"""
from __future__ import annotations


import tests.system.helpers as helpers


class TestSpawnCommand:
    async def test_spawn_mock_agent(self, unused_tcp_port):
        """/spawn mock starts a mock agent and produces a spawn event."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/spawn mock")
        await h_writer.drain()

        spawn = await helpers.read_until(h_reader, t="spawn", timeout=12.0)
        assert spawn["agent_type"] == "LLMAgent"
        h_writer.close()
        # Terminate subprocesses spawned into the server so they don't leak between tests
        import os
        import signal
        for pid in server._spawned_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    async def test_spawn_status_message_returned(self, unused_tcp_port):
        """/spawn returns a status message before the agent connects."""
        _server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/spawn mock")
        await h_writer.drain()

        # Server sends a status frame immediately, then spawn when subprocess connects
        status = await helpers.read_until(h_reader, t="status", timeout=5.0)
        assert status.get("text")
        h_writer.close()


class TestSwitchCommand:
    async def test_switch_sets_current_agent(self, unused_tcp_port):
        """/switch <id> returns a switch event with current_agent set."""
        _server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        # Spawn an agent to switch to
        helpers.send_cmd(h_writer, "/spawn mock")
        await h_writer.drain()
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=12.0)
        agent_id = spawn["agent_id"]

        # When a new LLM agent connects, the server auto-switches the human
        # client to the new agent. Consume that switch event first.
        await helpers.read_until(h_reader, t="switch", timeout=5.0)

        # Now send an explicit /switch to the raw agent_id (no room prefix).
        helpers.send_cmd(h_writer, f"/switch {agent_id}")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="switch", timeout=3.0)
        assert ev["current_agent"] == agent_id
        h_writer.close()

    async def test_switch_unknown_agent_rejected(self, unused_tcp_port):
        """/switch rejects unknown agents — only valid chat targets are accepted."""
        _server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/switch nonexistent-agent")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "not a chat target" in ev.get("text", "").lower()
        h_writer.close()


class TestUnknownAndErrorCommands:
    async def test_unknown_command_returns_unsupported(self, unused_tcp_port):
        """/bogus returns 'Unsupported server command: /bogus'."""
        _server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/boguscmd")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "unsupported" in ev.get("text", "").lower()
        h_writer.close()

    async def test_message_to_unknown_target(self, unused_tcp_port):
        """Sending a msg to an unknown agent returns a status error."""
        _server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_msg(h_writer, "no-such-agent", "hello")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "unknown" in ev.get("text", "").lower()
        h_writer.close()
