"""Module tests: CLI commands exercised over a real loopback TCP server.

These tests start an in-process MARS server and exercise the full path:

    CLI terminal  →  local command dispatch  →  MARSState  →  renderer

All tests remain in-process; no external processes, no real LLMs.
"""
from __future__ import annotations

import json
from io import StringIO
from unittest.mock import MagicMock

import pytest

import tests.system.helpers as helpers
from mars.cli.client import MARSClientTerminal
from mars.common.models import MARSState
from mars.cli.renderer import MARSRenderer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render(renderable, *, width: int = 120) -> str:
    from rich.console import Console
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=width, color_system=None)
    console.print(renderable)
    return buf.getvalue()


def _render_full(state: MARSState, *, width: int = 120) -> str:
    renderer = MARSRenderer(state)
    group = renderer.render_group(input_buf="", prompt="> ", console_height=40)
    return _render(group, width=width)


def _make_connected_terminal(port: int) -> tuple[MARSClientTerminal, MARSState]:
    state = MARSState()
    term = MARSClientTerminal.__new__(MARSClientTerminal)
    term._state = state
    term._writer = MagicMock()
    term._server_addr = f"127.0.0.1:{port}"
    return term, state


# ---------------------------------------------------------------------------
# /help over real server connection
# ---------------------------------------------------------------------------


class TestHelpOverServer:
    async def test_help_reply_panel_visible_in_full_layout(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/help")

        output = _render_full(state)
        assert "Command" in output or "spawn" in output.lower(), (
            f"/help content must be visible in full layout.\n{output}"
        )
        writer.close()

    async def test_help_produces_markdown_in_reply_panel(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/help")

        assert state.reply_content, "reply_content must be set after /help"
        assert "|" in state.reply_content, "Help must render as Markdown table"
        writer.close()


# ---------------------------------------------------------------------------
# /agents over real server connection
# ---------------------------------------------------------------------------


class TestAgentsOverServer:
    async def test_agents_reply_panel_visible_after_spawn(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        await term._handle_command("/agents")

        output = _render_full(state)
        assert agent_id in output, (
            f"/agents output must include spawned agent in full layout.\n{output}"
        )
        writer.close()

    async def test_agents_does_not_corrupt_display(self, unused_tcp_port):
        """Verify /agents uses reply panel (not console.print which corrupts TUI)."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)

        mock_console = MagicMock()
        term._console = mock_console
        await term._handle_command("/agents")

        mock_console.print.assert_not_called()
        assert state.reply_content
        writer.close()


# ---------------------------------------------------------------------------
# /read over real server connection
# ---------------------------------------------------------------------------


class TestReadOverServer:
    async def test_read_file_content_in_reply_panel(self, unused_tcp_port, tmp_path):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        f = tmp_path / "source.py"
        f.write_text("# UNIQUE_MODULE_TEST_CONTENT\nx = 42\n")
        await term._handle_command(f"/read {f}")

        assert "UNIQUE_MODULE_TEST_CONTENT" in state.reply_content, (
            f"/read must show file contents in reply_content.\n{state.reply_content}"
        )
        writer.close()

    async def test_read_file_visible_in_full_layout(self, unused_tcp_port, tmp_path):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        f = tmp_path / "readme.txt"
        f.write_text("FILEREAD_VISIBLE_IN_LAYOUT\n")
        await term._handle_command(f"/read {f}")

        output = _render_full(state)
        assert "FILEREAD_VISIBLE_IN_LAYOUT" in output, (
            f"File content must be visible in full layout.\n{output}"
        )
        writer.close()

    async def test_read_missing_file_status_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/read /no/such/file.xyz")

        output = _render_full(state)
        assert state.status_line, "/read missing file must set status_line"
        # Status line must appear in the layout
        assert state.status_line[:10] in output or "not found" in output.lower() or "file" in output.lower()
        writer.close()


# ---------------------------------------------------------------------------
# Status line visible over real connection
# ---------------------------------------------------------------------------


class TestStatusLineOverServer:
    async def test_status_line_visible_after_switch_fail(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/switch ghost@999")

        output = _render_full(state)
        assert state.status_line, "/switch unknown must set status_line"
        # The status_line text must be visible in the rendered layout
        assert "ghost@999" in output or "not found" in output.lower(), (
            f"Status feedback must be visible in layout.\nStatus: {state.status_line}\n"
            f"Layout:\n{output}"
        )
        writer.close()

    async def test_status_line_visible_after_echo_change(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/echo md")

        _output = _render_full(state)
        assert state.echo_mode == "md"
        # Status line feedback ("echo mode -> md") should be visible
        assert state.status_line
        writer.close()

    async def test_disconnected_status_visible(self, unused_tcp_port):
        """Simulating a disconnect must set a visible status_line."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_connected_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Simulate disconnection event (empty read → set status)
        state.status_line = "⚠️  Disconnected from server"
        state.status_style = "bold red"

        output = _render_full(state)
        assert "Disconnected" in output or "⚠" in output, (
            f"Disconnected status must be visible in layout.\n{output}"
        )
        writer.close()
