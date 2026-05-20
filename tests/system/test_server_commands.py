"""System tests: server command validation.

Exercises all server-side commands (/spawn, /switch, /join, /part, /list,
unknown commands) and message routing via the TCP wire protocol.

No external services required — uses the mock provider and offline helpers.
"""
from __future__ import annotations

import pytest
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
        import os, signal
        for pid in server._spawned_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    async def test_spawn_status_message_returned(self, unused_tcp_port):
        """/spawn returns a status message before the agent connects."""
        server = await helpers.start_server(unused_tcp_port)
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
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        # Spawn an agent to switch to
        helpers.send_cmd(h_writer, "/spawn mock")
        await h_writer.drain()
        spawn = await helpers.read_until(h_reader, t="spawn", timeout=12.0)
        agent_id = spawn["agent_id"]

        # When a new LLM agent connects, the server auto-switches the human
        # client to the agent's room (#<agent_id>). Consume that event first.
        await helpers.read_until(h_reader, t="switch", timeout=5.0)

        # Now send an explicit /switch to the raw agent_id (no room prefix).
        helpers.send_cmd(h_writer, f"/switch {agent_id}")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="switch", timeout=3.0)
        assert ev["current_agent"] == agent_id
        h_writer.close()

    async def test_switch_unknown_agent_still_switches(self, unused_tcp_port):
        """/switch accepts any id (server does not validate existence)."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/switch nonexistent-agent")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="switch", timeout=3.0)
        assert ev["current_agent"] == "nonexistent-agent"
        h_writer.close()


class TestJoinPartListCommands:
    async def test_join_switches_to_room(self, unused_tcp_port):
        """/join <room> returns a switch event with current_agent=#room."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/join test-room")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="switch", timeout=3.0)
        assert ev["current_agent"] == "#test-room"
        h_writer.close()

    async def test_part_emits_room_part_event(self, unused_tcp_port):
        """/part after /join emits a room_part event."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/join myroom")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="switch")  # consume join's switch event

        helpers.send_cmd(h_writer, "/part")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="room_part", timeout=3.0)
        assert ev["room"] == "myroom"
        h_writer.close()

    async def test_part_without_room_returns_status(self, unused_tcp_port):
        """/part when not in any room returns a status message."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/part")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "room" in ev.get("text", "").lower()
        h_writer.close()

    async def test_list_no_rooms(self, unused_tcp_port):
        """/list with no rooms returns 'No active rooms'."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/list")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "no active rooms" in ev.get("text", "").lower()
        h_writer.close()

    async def test_list_shows_joined_room(self, unused_tcp_port):
        """/list after /join shows the room in the listing."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/join alpha-room")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="switch")

        helpers.send_cmd(h_writer, "/list")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "alpha-room" in ev.get("text", "")
        h_writer.close()


class TestUnknownAndErrorCommands:
    async def test_unknown_command_returns_unsupported(self, unused_tcp_port):
        """/bogus returns 'Unsupported server command: /bogus'."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/boguscmd")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "unsupported" in ev.get("text", "").lower()
        h_writer.close()

    async def test_message_to_unknown_target(self, unused_tcp_port):
        """Sending a msg to an unknown agent returns a status error."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_msg(h_writer, "no-such-agent", "hello")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "unknown" in ev.get("text", "").lower()
        h_writer.close()

    async def test_join_no_args_returns_usage(self, unused_tcp_port):
        """/join with no room name returns a usage status message."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/join")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "usage" in ev.get("text", "").lower()
        h_writer.close()
