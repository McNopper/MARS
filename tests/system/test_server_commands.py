"""System tests: server command validation.

Exercises all server-side commands (/spawn, /switch, /join, /part, /list,
unknown commands) and message routing via the TCP wire protocol.

No external services required — uses the mock provider and offline helpers.
"""
from __future__ import annotations

import asyncio
import json

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
    async def test_switch_sets_current_room(self, unused_tcp_port):
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


class TestRoomMembership:
    """Room join/leave correctness.

    Key invariant: joining a room never spawns a new agent instance.
    An existing agent simply becomes a member of an additional room.
    """

    async def test_join_emits_room_join_event_with_members(self, unused_tcp_port):
        """After /join, the joiner receives a room_join event listing all members."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        welcome = await helpers.read_until(h_reader, t="welcome")
        my_id = welcome["your_id"]

        helpers.send_cmd(h_writer, "/join lobby")
        await h_writer.drain()

        ev = await helpers.read_until(h_reader, t="room_join", timeout=3.0)
        assert ev["room"] == "lobby"
        assert my_id in ev["members"]
        h_writer.close()

    async def test_extra_agent_added_to_room_without_new_spawn(self, unused_tcp_port):
        """Adding an existing agent to a room via /join does not spawn a new instance.

        This verifies the critical invariant: '/join room agent-id' only adds
        agent-id to the room — it does NOT create a second instance of the agent.
        """
        server = await helpers.start_server(unused_tcp_port)

        # Connect a service agent (not LLM, so no auto-room is created)
        bot_reader, bot_writer = await helpers.connect(
            unused_tcp_port, "bot-service", role="agent", agent_type="ServiceAgent"
        )
        bot_welcome = await helpers.read_until(bot_reader, t="welcome")
        bot_id = bot_welcome["your_id"]

        # Connect the human
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        # Record agent count before the join
        agent_count_before = len(server._state.agents)

        # Human invites the bot into a room
        helpers.send_cmd(h_writer, f"/join collab-room {bot_id}")
        await h_writer.drain()

        # Consume join events for a short window; no spawn must appear
        events: list[dict] = []
        try:
            while True:
                raw = await asyncio.wait_for(h_reader.readline(), timeout=0.5)
                events.append(json.loads(raw))
        except asyncio.TimeoutError:
            pass

        spawn_events = [e for e in events if e.get("t") == "spawn"]
        assert not spawn_events, (
            f"Unexpected spawn event(s) when adding existing agent to room: {spawn_events}"
        )

        # Agent count must be unchanged
        agent_count_after = len(server._state.agents)
        assert agent_count_after == agent_count_before, (
            f"Agent count changed from {agent_count_before} to {agent_count_after} "
            "— a new instance was spawned instead of joining the room"
        )

        # The bot should now be in the room
        assert bot_id in server._rooms.get("collab-room", set()), (
            f"bot {bot_id!r} not in room 'collab-room'; rooms: {dict(server._rooms)}"
        )

        h_writer.close()
        bot_writer.close()

    async def test_both_agents_receive_room_join_notification(self, unused_tcp_port):
        """Both the inviting human and the invited agent receive room_join events."""
        server = await helpers.start_server(unused_tcp_port)

        bot_reader, bot_writer = await helpers.connect(
            unused_tcp_port, "bot-b", role="agent", agent_type="ServiceAgent"
        )
        bot_welcome = await helpers.read_until(bot_reader, t="welcome")
        bot_id = bot_welcome["your_id"]

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "alice")
        # read_initial_events drains everything up to and including "welcome"
        initial = await helpers.read_initial_events(h_reader)
        h_welcome = next(e for e in initial if e.get("t") == "welcome")
        human_id = h_welcome["your_id"]

        helpers.send_cmd(h_writer, f"/join shared-room {bot_id}")
        await h_writer.drain()

        # Server sends room_join twice: first when alice joins (members=[alice]),
        # then again when bot joins (members=[alice, bot]).  Wait for the second.
        ev_human = await helpers.read_until(h_reader, t="room_join", timeout=3.0)
        while bot_id not in ev_human.get("members", []):
            ev_human = await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        assert human_id in ev_human["members"]
        assert bot_id in ev_human["members"]

        # Bot should also get a room_join notification
        ev_bot = await helpers.read_until(bot_reader, t="room_join", timeout=3.0)
        assert ev_bot["room"] == "shared-room"
        assert bot_id in ev_bot["members"]

        h_writer.close()
        bot_writer.close()

    async def test_join_same_room_twice_is_idempotent(self, unused_tcp_port):
        """Joining the same room twice does not duplicate the member."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        welcome = await helpers.read_until(h_reader, t="welcome")
        my_id = welcome["your_id"]

        helpers.send_cmd(h_writer, "/join alpha")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        helpers.send_cmd(h_writer, "/join alpha")
        await h_writer.drain()
        ev = await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        members = ev["members"]
        assert members.count(my_id) == 1, (
            f"Agent appears {members.count(my_id)} times in room — expected exactly 1"
        )
        h_writer.close()

    async def test_part_named_room_removes_only_that_room(self, unused_tcp_port):
        """/part <room-name> leaves the named room only."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        welcome = await helpers.read_until(h_reader, t="welcome")
        my_id = welcome["your_id"]

        # Join two rooms
        helpers.send_cmd(h_writer, "/join room-one")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        helpers.send_cmd(h_writer, "/join room-two")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        # Part only room-one
        helpers.send_cmd(h_writer, "/part room-one")
        await h_writer.drain()
        ev = await helpers.read_until(h_reader, t="room_part", timeout=3.0)

        assert ev["room"] == "room-one"
        # Agent should still be in room-two
        assert my_id in server._rooms.get("room-two", set()), "agent was unexpectedly removed from room-two"
        assert my_id not in server._rooms.get("room-one", set()), "agent still in room-one after /part"

        h_writer.close()

    async def test_room_deleted_after_last_member_parts(self, unused_tcp_port):
        """Room is removed from server state once all members leave."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/join temp-room")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        assert "temp-room" in server._rooms, "room should exist after joining"

        helpers.send_cmd(h_writer, "/part temp-room")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="room_part", timeout=3.0)

        assert "temp-room" not in server._rooms, "empty room should be deleted from server state"

        h_writer.close()

    async def test_agent_disconnect_triggers_room_part_for_remaining_members(self, unused_tcp_port):
        """When a room member disconnects, remaining members receive a room_part event."""
        server = await helpers.start_server(unused_tcp_port)

        bot_reader, bot_writer = await helpers.connect(
            unused_tcp_port, "leaver", role="agent", agent_type="ServiceAgent"
        )
        bot_welcome = await helpers.read_until(bot_reader, t="welcome")
        bot_id = bot_welcome["your_id"]

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "watcher")
        # read_initial_events drains everything up to and including "welcome",
        # consuming the bot's spawn event that arrives before welcome.
        await helpers.read_initial_events(h_reader)

        # Add both to the same room
        helpers.send_cmd(h_writer, f"/join exit-room {bot_id}")
        await h_writer.drain()

        # Consume room_join events
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)
        try:
            await helpers.read_until(h_reader, t="room_join", timeout=1.0)
        except (TimeoutError, asyncio.TimeoutError):
            pass  # second room_join may already have arrived

        # Bot disconnects
        bot_writer.close()

        # Watcher should receive a room_part event for the bot
        ev = await helpers.read_until(h_reader, t="room_part", timeout=5.0)
        assert ev["room"] == "exit-room"
        assert ev["member"] == bot_id

        h_writer.close()

    async def test_unknown_agent_id_in_join_returns_status(self, unused_tcp_port):
        """/join room ghost-id returns a status error for the unknown agent."""
        server = await helpers.start_server(unused_tcp_port)
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        helpers.send_cmd(h_writer, "/join myroom ghost-agent@99")
        await h_writer.drain()

        # Consume the human's own room_join first
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)

        ev = await helpers.read_until(h_reader, t="status", timeout=3.0)
        assert "ghost-agent@99" in ev.get("text", ""), (
            f"Expected error mentioning unknown agent ID; got: {ev.get('text')}"
        )
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


class TestMultiAgentRoom:
    """Three-way room: user + copilot-like agent + ollama-like agent.

    These tests use lightweight mock wire agents (no real LLM calls) to
    verify the room membership and notification invariants that matter when
    two AI agents and one human share a room.
    """

    async def test_three_members_all_appear_in_room_join(self, unused_tcp_port):
        """User + copilot-mock + ollama-mock all join; room_join lists all three."""
        server = await helpers.start_server(unused_tcp_port)

        # Copilot-like agent (LLM wire agent)
        cp_reader, cp_writer = await helpers.connect(
            unused_tcp_port, "copilot-agent", role="agent", agent_type="LLMAgent"
        )
        cp_welcome = await helpers.read_until(cp_reader, t="welcome")
        cp_id = cp_welcome["your_id"]

        # Ollama-like agent (LLM wire agent)
        ol_reader, ol_writer = await helpers.connect(
            unused_tcp_port, "ollama-agent", role="agent", agent_type="LLMAgent"
        )
        ol_welcome = await helpers.read_until(ol_reader, t="welcome")
        ol_id = ol_welcome["your_id"]

        # Human connects — consumes welcome + any auto-join spawn events
        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial = await helpers.read_initial_events(h_reader)
        h_welcome = next(e for e in initial if e.get("t") == "welcome")
        h_id = h_welcome["your_id"]

        # Human creates the room and adds both agents
        helpers.send_cmd(h_writer, f"/join collab {cp_id} {ol_id}")
        await h_writer.drain()

        # Wait for the room_join that includes all three members
        ev = await helpers.read_until(h_reader, t="room_join", timeout=5.0)
        while not ({h_id, cp_id, ol_id} <= set(ev.get("members", []))):
            ev = await helpers.read_until(h_reader, t="room_join", timeout=5.0)

        members = set(ev["members"])
        assert h_id in members,  f"human {h_id!r} missing from room; members={members}"
        assert cp_id in members, f"copilot {cp_id!r} missing from room; members={members}"
        assert ol_id in members, f"ollama {ol_id!r} missing from room; members={members}"

        h_writer.close()
        cp_writer.close()
        ol_writer.close()

    async def test_all_three_members_on_server_side(self, unused_tcp_port):
        """Server _rooms state contains all three agent IDs after /join."""
        server = await helpers.start_server(unused_tcp_port)

        cp_reader, cp_writer = await helpers.connect(
            unused_tcp_port, "copilot-agent", role="agent", agent_type="LLMAgent"
        )
        cp_id = (await helpers.read_until(cp_reader, t="welcome"))["your_id"]

        ol_reader, ol_writer = await helpers.connect(
            unused_tcp_port, "ollama-agent", role="agent", agent_type="LLMAgent"
        )
        ol_id = (await helpers.read_until(ol_reader, t="welcome"))["your_id"]

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        h_id = (await helpers.read_until(h_reader, t="welcome"))["your_id"]

        helpers.send_cmd(h_writer, f"/join team-room {cp_id} {ol_id}")
        await h_writer.drain()

        # Drain until all three are in the room on the server side
        deadline = asyncio.get_event_loop().time() + 5.0
        while asyncio.get_event_loop().time() < deadline:
            room = server._rooms.get("team-room", set())
            if {h_id, cp_id, ol_id} <= room:
                break
            await asyncio.sleep(0.05)

        room = server._rooms.get("team-room", set())
        assert h_id in room,  f"human not in server room; room={room}"
        assert cp_id in room, f"copilot not in server room; room={room}"
        assert ol_id in room, f"ollama not in server room; room={room}"

        h_writer.close()
        cp_writer.close()
        ol_writer.close()

    async def test_both_agents_notified_when_third_joins(self, unused_tcp_port):
        """Each agent already in the room is notified when the third joins."""
        server = await helpers.start_server(unused_tcp_port)

        cp_reader, cp_writer = await helpers.connect(
            unused_tcp_port, "copilot-agent", role="agent", agent_type="LLMAgent"
        )
        cp_id = (await helpers.read_until(cp_reader, t="welcome"))["your_id"]

        ol_reader, ol_writer = await helpers.connect(
            unused_tcp_port, "ollama-agent", role="agent", agent_type="LLMAgent"
        )
        ol_id = (await helpers.read_until(ol_reader, t="welcome"))["your_id"]

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        await helpers.read_until(h_reader, t="welcome")

        # Human joins with copilot first, then adds ollama
        helpers.send_cmd(h_writer, f"/join team {cp_id}")
        await h_writer.drain()
        await helpers.read_until(h_reader, t="room_join", timeout=3.0)
        await helpers.read_until(cp_reader, t="room_join", timeout=3.0)

        helpers.send_cmd(h_writer, f"/join team {ol_id}")
        await h_writer.drain()

        # Copilot (already in room) receives notification that ollama joined
        ev_cp = await helpers.read_until(cp_reader, t="room_join", timeout=3.0)
        while ol_id not in ev_cp.get("members", []):
            ev_cp = await helpers.read_until(cp_reader, t="room_join", timeout=3.0)
        assert ol_id in ev_cp["members"], (
            f"Copilot not notified that ollama joined; members={ev_cp['members']}"
        )
        assert cp_id in ev_cp["members"]

        # Ollama receives its own join notification
        ev_ol = await helpers.read_until(ol_reader, t="room_join", timeout=3.0)
        assert ol_id in ev_ol["members"]

        h_writer.close()
        cp_writer.close()
        ol_writer.close()

    async def test_client_state_shows_three_members(self, unused_tcp_port):
        """The CLI state.rooms dict reflects all three members after room_join events."""
        from mars.client.cli.client import MARSClientTerminal
        from mars.client.cli.models import MARSState

        server = await helpers.start_server(unused_tcp_port)

        cp_reader, cp_writer = await helpers.connect(
            unused_tcp_port, "copilot-agent", role="agent", agent_type="LLMAgent"
        )
        cp_id = (await helpers.read_until(cp_reader, t="welcome"))["your_id"]

        ol_reader, ol_writer = await helpers.connect(
            unused_tcp_port, "ollama-agent", role="agent", agent_type="LLMAgent"
        )
        ol_id = (await helpers.read_until(ol_reader, t="welcome"))["your_id"]

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        h_id = (await helpers.read_until(h_reader, t="welcome"))["your_id"]

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state

        helpers.send_cmd(h_writer, f"/join collab {cp_id} {ol_id}")
        await h_writer.drain()

        # Consume room_join events until the collab room shows all three members
        ev = await helpers.read_until(h_reader, t="room_join", timeout=5.0)
        while ev.get("room") != "collab" or not ({h_id, cp_id, ol_id} <= set(ev.get("members", []))):
            ev = await helpers.read_until(h_reader, t="room_join", timeout=5.0)

        # Apply the final room_join event to the CLI state
        term._apply_event(ev)

        members = state.rooms.get("collab", set())
        assert h_id in members,  f"human missing from client state.rooms; members={members}"
        assert cp_id in members, f"copilot missing from client state.rooms; members={members}"
        assert ol_id in members, f"ollama missing from client state.rooms; members={members}"
        assert state.current_room == "collab"

        h_writer.close()
        cp_writer.close()
        ol_writer.close()
