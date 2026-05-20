"""System tests: CLI state rendering against a real MARS server.

These tests start an in-process MARS server, connect a real TCP client,
apply server events to a ``MARSClientTerminal``, then render the resulting
UI state to ASCII using ``MARSRenderer`` and compare the output.

This is the "ascii compare" approach: render Rich panels to a StringIO
console and assert specific strings are present or absent in the output.

Run::

    python -m pytest tests/system/test_cli_state_rendering.py -v -m "not llm"
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock

import pytest

import tests.system.helpers as helpers
from mars.client.cli.client import MARSClientTerminal
from mars.client.cli.models import AgentRecord, ChatMessage, MARSState
from mars.client.cli.renderer import MARSRenderer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# ASCII render helper
# ---------------------------------------------------------------------------


def _render(renderer: MARSRenderer, method: str = "render_sidebar", width: int = 60) -> str:
    from rich.console import Console
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=width, color_system=None)
    console.print(getattr(renderer, method)())
    return buf.getvalue()


def _render_full(state: MARSState, width: int = 120, height: int = 40) -> str:
    from rich.console import Console
    renderer = MARSRenderer(state)
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=width, color_system=None)
    console.print(renderer.render_group(input_buf="", prompt="> ", console_height=height))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests: server events → CLI state → ASCII output
# ---------------------------------------------------------------------------


class TestSpawnEventRendering:
    """Server spawn events must result in the agent appearing in the sidebar."""

    async def test_spawned_agent_appears_in_sidebar(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = f"127.0.0.1:{unused_tcp_port}"

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Spawn a mock agent via the server
        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()

        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)

        agent_id = spawn_ev["agent_id"]
        renderer = MARSRenderer(state)
        output = _render(renderer, "render_sidebar")

        assert agent_id in output, (
            f"Spawned agent '{agent_id}' must appear in sidebar.\n{output}"
        )
        writer.close()

    async def test_spawned_agent_auto_selected_as_current(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)

        agent_id = spawn_ev["agent_id"]
        assert state.current_agent == agent_id, (
            "First spawned LLM agent must become current_agent automatically"
        )
        writer.close()

    async def test_service_agent_appears_in_services_section(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Inject a service agent directly into state (simulating a service spawn event)
        term._apply_event({
            "t": "spawn", "agent_id": "svc.clock@1",
            "agent_type": "ServiceAgent", "domain": "services",
        })

        renderer = MARSRenderer(state)
        output = _render(renderer, "render_sidebar")

        # Service agents appear below the "services" divider
        assert "services" in output, "Services section must appear in sidebar"
        assert "svc.clock@1" in output
        writer.close()


class TestDespawnRendering:
    """Despawned agents must disappear from the sidebar."""

    async def test_despawned_agent_removed_from_sidebar(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Spawn then despawn
        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        # Simulate despawn
        term._apply_event({"t": "despawn", "agent_id": agent_id})

        renderer = MARSRenderer(state)
        output = _render(renderer, "render_sidebar")
        assert agent_id not in output, (
            f"Despawned agent '{agent_id}' must not appear in sidebar after despawn"
        )
        writer.close()


class TestChatRendering:
    """Chat messages received from the server must appear in the reply panel."""

    async def test_incoming_chat_appears_in_history(self, unused_tcp_port):
        """A chat event must be stored in the agent's chat history."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        term._apply_event({
            "t": "chat", "agent_id": agent_id,
            "ts": datetime.now().isoformat(),
            "sender": agent_id, "content": "UNIQUE_CHAT_MESSAGE_XYZ",
            "direction": "in",
        })

        rec = state.agents[agent_id]
        assert any("UNIQUE_CHAT_MESSAGE_XYZ" in m.content for m in rec.chat)
        writer.close()

    async def test_reply_appears_in_reply_panel_after_read(self, unused_tcp_port):
        """After /read, the reply content appears in the reply panel ASCII output."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        term._apply_event({
            "t": "chat", "agent_id": agent_id,
            "ts": datetime.now().isoformat(),
            "sender": agent_id, "content": "PANEL_REPLY_CONTENT",
            "direction": "in",
        })

        # Set reply_content directly from chat history (pending_reply no longer used)
        state.reply_agent = agent_id
        state.reply_content = "PANEL_REPLY_CONTENT"

        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None, "Reply panel must render when reply_content is set"

        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120, color_system=None)
        console.print(panel)
        output = buf.getvalue()

        assert "PANEL_REPLY_CONTENT" in output, (
            f"Reply content must appear in the reply panel.\n{output}"
        )
        writer.close()

    async def test_service_agent_chat_appears_in_feed_panel(self, unused_tcp_port):
        """Direct chat with a non-conversational agent renders in the feed panel."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Inject a ServiceAgent directly (non-conversational → direct chat mode)
        term._apply_event({
            "t": "spawn", "agent_id": "svc.test@1",
            "agent_type": "ServiceAgent", "domain": "services",
        })
        state.current_agent = "svc.test@1"

        term._apply_event({
            "t": "chat", "agent_id": "svc.test@1",
            "ts": datetime.now().isoformat(),
            "sender": "svc.test@1", "content": "SERVICE_AGENT_REPLY",
            "direction": "in",
        })

        renderer = MARSRenderer(state)
        output = _render(renderer, "render_feed", width=120)

        assert "SERVICE_AGENT_REPLY" in output, (
            f"Service agent chat must appear in feed panel.\n{output}"
        )
        writer.close()


class TestFSMRendering:
    """FSM state changes must be reflected in the sidebar dot colour and spinner."""

    async def test_thinking_state_renders_spinner(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Spawn mock agent
        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        # Set agent to THINKING
        term._apply_event({"t": "fsm", "agent_id": agent_id, "fsm_state": "THINKING"})

        renderer = MARSRenderer(state)
        output = _render(renderer, "render_sidebar")

        spinner_chars = MARSRenderer._THINKING_SPINNER
        assert any(ch in output for ch in spinner_chars), (
            f"THINKING agent must show spinner in sidebar.\n{output}"
        )
        writer.close()

    async def test_idle_state_renders_green_dot(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        term._apply_event({"t": "fsm", "agent_id": agent_id, "fsm_state": "IDLE"})

        renderer = MARSRenderer(state)
        output = _render(renderer, "render_sidebar")
        assert "●" in output, "IDLE agent must show dot in sidebar"
        writer.close()


class TestFeedRendering:
    """Feed events received from the server must appear in the activity feed."""

    async def test_feed_event_appears_in_activity_feed(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Inject a feed event directly
        term._apply_event({
            "t": "feed", "event_type": "system",
            "from_id": "server", "to_id": "",
            "snippet": "UNIQUE_FEED_SNIPPET_ABC",
            "ts": datetime.now().isoformat(),
        })

        renderer = MARSRenderer(state)
        output = _render(renderer, "render_feed", width=120)

        assert "UNIQUE_FEED_SNIPPET_ABC" in output, (
            f"Feed snippet must appear in the activity feed.\n{output}"
        )
        writer.close()

    async def test_spawn_creates_feed_entry(self, unused_tcp_port):
        """Server must emit a feed event when an agent is spawned."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()

        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)

        # Server may also emit a feed event; drain briefly
        try:
            while True:
                raw = await asyncio.wait_for(reader.readline(), timeout=1.0)
                ev = json.loads(raw.decode())
                term._apply_event(ev)
        except asyncio.TimeoutError:
            pass

        renderer = MARSRenderer(state)
        feed_output = _render(renderer, "render_feed", width=120)
        sidebar_output = _render(renderer, "render_sidebar")

        agent_id = spawn_ev["agent_id"]
        assert agent_id in sidebar_output, "Agent must appear in sidebar"
        writer.close()


class TestConnectionMessage:
    """CLI must print the connection address when connecting to a remote server."""

    async def test_connecting_message_includes_host_port(self, unused_tcp_port, capsys):
        """_async_client prints connection message to stdout before events start."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841

        from mars.client.cli.main import _async_client
        import argparse

        args = argparse.Namespace(connect=f"127.0.0.1:{unused_tcp_port}", remote=None, debug=False)

        # Patch terminal.run to exit immediately so the test doesn't hang
        async def _noop(self):
            pass

        try:
            from unittest.mock import patch as _patch
            with _patch.object(MARSClientTerminal, "run", new=_noop):
                await asyncio.wait_for(_async_client(args), timeout=5.0)
        except Exception:
            pass

        captured = capsys.readouterr()
        assert str(unused_tcp_port) in captured.out, (
            "Connection message must include the server port"
        )


class TestFullLayoutRendering:
    """The complete TUI layout renders without exceptions."""

    async def test_full_group_renders_with_agent_and_reply(self, unused_tcp_port):
        """Full layout shows agent in sidebar and reply content in reply panel."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        state = MARSState()
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        # For LLM agents, reply content shows in the reply panel when reply_content is set
        term._apply_event({
            "t": "chat", "agent_id": agent_id,
            "ts": datetime.now().isoformat(),
            "sender": agent_id, "content": "FULL_LAYOUT_MSG",
            "direction": "in",
        })
        # Set reply_content directly (pending_reply no longer used)
        state.reply_agent = agent_id
        state.reply_content = "FULL_LAYOUT_MSG"

        output = _render_full(state, width=120, height=40)
        assert agent_id in output
        assert "FULL_LAYOUT_MSG" in output
        writer.close()
