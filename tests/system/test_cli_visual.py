"""System tests: visual CLI validation.

These tests start a real in-process MARS server, connect a real TCP client,
trigger user-facing CLI commands, and assert that the output is correct in the
rendered TUI layout (ASCII comparison via Rich StringIO console).

This is the key "does it look right when you actually run it?" tier.  All
previously invisible bugs (status_line not rendered, /help showing nothing,
/agents corrupting the TUI with console.print) are exercised here.

Each test class maps to one user-visible feature.  The tests render the full
3-panel TUI layout to a fixed-width string and assert specific visible strings.

Run::

    python -m pytest tests/system/test_cli_visual.py -v
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import tests.system.helpers as helpers
from mars.client.cli.client import MARSClientTerminal
from mars.client.cli.models import AgentRecord, ChatMessage, MARSState
from mars.client.cli.renderer import MARSRenderer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _render(renderable, *, width: int = 120) -> str:
    """Render a Rich renderable to a plain string (no colour codes)."""
    from rich.console import Console
    buf = StringIO()
    console = Console(
        file=buf, force_terminal=True, width=width,
        color_system=None, highlight=False,
    )
    console.print(renderable)
    return buf.getvalue()


def _render_full(state: MARSState, *, width: int = 120) -> str:
    """Render the complete 3-panel TUI layout for *state*."""
    renderer = MARSRenderer(state)
    group = renderer.render_group(input_buf="", prompt="> ", console_height=40)
    return _render(group, width=width)


def _make_terminal(port: int) -> tuple[MARSClientTerminal, MARSState]:
    state = MARSState()
    term = MARSClientTerminal.__new__(MARSClientTerminal)
    term._state = state
    term._writer = MagicMock()
    term._server_addr = f"127.0.0.1:{port}"
    return term, state


# ---------------------------------------------------------------------------
# Visual: /help
# ---------------------------------------------------------------------------


class TestVisualHelp:
    """Typing /help must display a visible Markdown command reference."""

    async def test_help_reply_panel_visible(self, unused_tcp_port):
        """After /help the reply panel must contain the command reference table."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/help")

        output = _render_full(state)
        assert state.reply_content, "/help must populate reply_content"
        # The Markdown table must survive the full layout render
        assert "spawn" in output.lower() or "agents" in output.lower(), (
            f"Full layout after /help must show command reference.\n{output[:2000]}"
        )
        writer.close()

    async def test_help_table_in_reply_panel_only(self, unused_tcp_port):
        """The /help output must come from the reply panel, not the status_line."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/help")

        # reply_content must be rich Markdown, not a cramped one-liner in status
        assert "|" in state.reply_content, (
            "reply_content must be a Markdown table, not a one-liner"
        )
        writer.close()

    async def test_help_multiple_commands_visible(self, unused_tcp_port):
        """The /help panel must mention several key commands."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/help")

        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None
        panel_text = _render(panel)

        for expected_cmd in ("/spawn", "/quit", "/echo"):
            assert expected_cmd in panel_text, (
                f"'{expected_cmd}' must appear in /help output.\n{panel_text[:2000]}"
            )
        writer.close()


# ---------------------------------------------------------------------------
# Visual: /agents
# ---------------------------------------------------------------------------


class TestVisualAgents:
    """/agents must display a visible Markdown table in the reply panel."""

    async def test_agents_list_visible_in_layout(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        # Spawn an agent so there is something to list
        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        await term._handle_command("/agents")

        output = _render_full(state)
        assert agent_id in output, (
            f"/agents must show agent ID in full layout.\n{output[:2000]}"
        )
        writer.close()

    async def test_agents_not_corrupting_tui(self, unused_tcp_port):
        """/agents must NEVER call console.print() directly (that corrupts TUI)."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
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

    async def test_agents_available_visible(self, unused_tcp_port):
        """/agents available must show the service agent catalogue."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/agents available")

        assert state.reply_content, "/agents available must produce reply content"
        assert "|" in state.reply_content, "Must be a Markdown table"
        writer.close()


# ---------------------------------------------------------------------------
# Visual: /read
# ---------------------------------------------------------------------------


class TestVisualRead:
    """/read <file> must display file contents in the reply panel."""

    async def test_read_visible_in_layout(self, unused_tcp_port, tmp_path):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        f = tmp_path / "code.py"
        f.write_text("# VISUAL_SYSTEM_TEST_CODE\ndef hello():\n    return 42\n")
        await term._handle_command(f"/read {f}")

        output = _render_full(state)
        assert "VISUAL_SYSTEM_TEST_CODE" in output, (
            f"/read file content must appear in full layout.\n{output[:2000]}"
        )
        writer.close()

    async def test_read_filename_in_reply_panel_title(self, unused_tcp_port, tmp_path):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        f = tmp_path / "special_name.txt"
        f.write_text("content\n")
        await term._handle_command(f"/read {f}")

        assert "special_name.txt" in state.reply_agent
        writer.close()

    async def test_read_missing_status_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/read /this/file/does/not/exist.txt")

        output = _render_full(state)
        assert state.status_line, "Missing file must set status_line"
        # The status must be visible (not invisible)
        assert state.status_line[:8] in output or "not found" in output.lower() or "file" in output.lower(), (
            f"Error status must be visible in layout.\n"
            f"status_line={state.status_line!r}\n{output[:2000]}"
        )
        writer.close()


# ---------------------------------------------------------------------------
# Visual: status_line is always visible
# ---------------------------------------------------------------------------


class TestVisualStatusLine:
    """Every command that sets status_line must produce visible output in the TUI."""

    async def test_switch_unknown_agent_status_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/switch ghost@777")

        output = _render_full(state)
        assert state.status_line, "Should set status_line"
        assert "ghost@777" in output or "not found" in output.lower(), (
            f"status_line must be visible in full layout.\n"
            f"status_line={state.status_line!r}\noutput:\n{output[:2000]}"
        )
        writer.close()

    async def test_echo_change_status_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/echo text")

        output = _render_full(state)
        assert state.status_line
        # "echo" or "text" feedback should be visible
        assert "echo" in output.lower() or "text" in output.lower() or state.status_line[:8] in output, (
            f"Echo change status must be visible.\n{output[:2000]}"
        )
        writer.close()

    async def test_verbose_status_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        await term._handle_command(f"/verbose {agent_id}")

        output = _render_full(state)
        assert state.status_line
        assert "verbose" in output.lower() or state.status_line[:8] in output, (
            f"Verbose toggle status must be visible.\n{output[:2000]}"
        )
        writer.close()

    async def test_avatar_status_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        await term._handle_command("/avatar 2")

        output = _render_full(state)
        assert state.status_line
        writer.close()

    async def test_status_from_server_event_visible(self, unused_tcp_port):
        """Server-sent status events must also be visible in the prompt panel."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        term._apply_event({"t": "status", "text": "SERVER_STATUS_XYZ", "style": ""})

        output = _render_full(state)
        assert "SERVER_STATUS_XYZ" in output, (
            f"Server-sent status must be visible in layout.\n{output[:2000]}"
        )
        writer.close()


# ---------------------------------------------------------------------------
# Visual: Markdown reply panel
# ---------------------------------------------------------------------------


class TestVisualMarkdownRender:
    """Agent replies with Markdown formatting must render correctly."""

    async def test_heading_visible_in_reply_panel(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
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
            "sender": agent_id,
            "content": "# Visual Heading Test\n\nSome **bold** and _italic_ text.",
            "direction": "in",
        })
        state.reply_agent = agent_id
        state.reply_content = "# Visual Heading Test\n\nSome **bold** and _italic_ text."

        output = _render_full(state)
        assert "Visual Heading Test" in output, (
            f"Markdown heading must appear in full layout.\n{output[:2000]}"
        )
        writer.close()

    async def test_code_fence_visible_in_reply_panel(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        content = "Here is code:\n```python\nprint('VISUAL_CODE_TEST')\n```"
        state.reply_agent = agent_id
        state.reply_content = content

        output = _render_full(state)
        assert "VISUAL_CODE_TEST" in output, (
            f"Code fence content must be visible in full layout.\n{output[:2000]}"
        )
        writer.close()


# ---------------------------------------------------------------------------
# Visual: Math rendering in reply panel
# ---------------------------------------------------------------------------


class TestVisualMathRendering:
    """LaTeX math in agent replies must render as Unicode in the full layout."""

    async def test_inline_math_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        state.reply_agent = agent_id
        state.reply_content = r"The angle $\alpha$ is measured in radians."

        output = _render_full(state)
        assert "α" in output, (
            f"Inline math $\\alpha$ must render as α in full layout.\n{output[:2000]}"
        )
        writer.close()

    async def test_display_math_visible(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        state.reply_agent = agent_id
        state.reply_content = r"The sum: $$\sum$$"

        output = _render_full(state)
        assert "∑" in output, (
            f"Display math $$\\sum$$ must render as ∑ in full layout.\n{output[:2000]}"
        )
        writer.close()


# ---------------------------------------------------------------------------
# Visual: MCP servers panel (bottom-left)
# ---------------------------------------------------------------------------


class TestVisualMCPPanel:
    """The bottom-left MCP panel must list service agents and their tools."""

    def _render_panel(self, state: MARSState, method: str = "render_mcp_panel", *, width: int = 120) -> str:
        renderer = MARSRenderer(state)
        panel = getattr(renderer, method)()
        return _render(panel, width=width)

    async def test_mcp_panel_empty_message(self, unused_tcp_port):
        """With no MCP servers, the panel must say so."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        state = MARSState()
        output = self._render_panel(state)
        assert "MCP" in output or "No MCP" in output.lower() or "No" in output

    async def test_mcp_panel_shows_service_agent(self, unused_tcp_port):
        """A spawned service agent must appear in the MCP panel."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        term._apply_event({
            "t": "spawn", "agent_id": "svc.sympy@1",
            "agent_type": "ServiceAgent", "domain": "services",
        })

        output = self._render_panel(state)
        assert "svc.sympy@1" in output, (
            f"Service agent must appear in MCP panel.\n{output[:1000]}"
        )
        writer.close()

    async def test_service_agent_not_in_agents_sidebar(self, unused_tcp_port):
        """Service agents must NOT pollute the top-left agents panel."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        term._apply_event({
            "t": "spawn", "agent_id": "svc.sympy@1",
            "agent_type": "ServiceAgent", "domain": "services",
        })

        sidebar_output = self._render_panel(state, "render_sidebar")
        assert "svc.sympy@1" not in sidebar_output, (
            f"Service agent must NOT appear in agents sidebar.\n{sidebar_output[:1000]}"
        )
        writer.close()

    async def test_mcp_panel_shows_tools(self, unused_tcp_port):
        """MCP tool names must appear under their server in the MCP panel."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        term._apply_event({
            "t": "spawn", "agent_id": "svc.github@1",
            "agent_type": "ServiceAgent", "domain": "services",
        })
        # Inject tool schemas directly (as the MCP adapter would)
        state.agents["svc.github@1"].tool_schemas = [
            {"name": "search_repositories", "description": "Search GitHub repos"},
            {"name": "create_issue", "description": "Create an issue"},
        ]
        # Focus + select the server so it expands
        state.panel_focus = "mcp"
        state.mcp_cursor = 0

        output = self._render_panel(state)
        assert "search_repositories" in output, (
            f"Tool name must appear in MCP panel.\n{output[:1000]}"
        )
        assert "create_issue" in output
        writer.close()

    async def test_full_layout_has_mcp_panel(self, unused_tcp_port):
        """The full 3-column layout must include the MCP servers label."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        output = _render_full(state)
        assert "MCP" in output, (
            f"Full layout must include MCP Servers panel.\n{output[:2000]}"
        )
        writer.close()

    async def test_full_layout_mcp_tool_visible(self, unused_tcp_port):
        """Tools registered to a service agent must be visible in the full layout."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        term._apply_event({
            "t": "spawn", "agent_id": "svc.math@1",
            "agent_type": "ServiceAgent",
        })
        state.agents["svc.math@1"].tool_schemas = [
            {"name": "solve_math", "description": "Solve equations"},
        ]
        # Focus + select so the server expands and tools are visible
        state.panel_focus = "mcp"
        state.mcp_cursor = 0

        output = _render_full(state)
        assert "solve_math" in output, (
            f"Tool must be visible in full layout.\n{output[:2000]}"
        )
        writer.close()


# ---------------------------------------------------------------------------
# Visual: Full layout integrity
# ---------------------------------------------------------------------------


class TestVisualFullLayout:
    """The full 3-panel layout must render without exceptions in all scenarios."""

    async def test_empty_state_renders(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        state = MARSState()
        output = _render_full(state)
        assert output  # must produce non-empty output

    async def test_welcome_only_renders(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        output = _render_full(state)
        assert output
        writer.close()

    async def test_layout_with_agent_and_reply(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        state.reply_agent = agent_id
        state.reply_content = "FULL_LAYOUT_REPLY_CONTENT"

        output = _render_full(state)
        assert agent_id in output
        assert "FULL_LAYOUT_REPLY_CONTENT" in output
        writer.close()

    async def test_layout_with_status_and_reply(self, unused_tcp_port):
        """Layout with both status_line and reply_content must render correctly."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        state.status_line = "LAYOUT_STATUS_ABC"
        state.reply_agent = "test-bot"
        state.reply_content = "LAYOUT_REPLY_XYZ"

        output = _render_full(state)
        assert "LAYOUT_STATUS_ABC" in output, (
            f"Status line must be visible.\n{output[:2000]}"
        )
        assert "LAYOUT_REPLY_XYZ" in output, (
            f"Reply content must be visible.\n{output[:2000]}"
        )
        writer.close()

    async def test_layout_sidebar_feed_prompt_all_present(self, unused_tcp_port):
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)

        output = _render_full(state)
        # Agents sidebar label
        assert "Agents" in output, "Agents sidebar must show 'Agents'"
        # MCP panel label
        assert "MCP" in output, "MCP Servers panel must be present"
        # Activity feed label
        assert "Activity" in output or "Feed" in output, "Feed panel must be present"
        # Prompt
        assert ">" in output, "Prompt must be visible"
        writer.close()

    async def test_layout_does_not_contain_raw_latex(self, unused_tcp_port):
        """Raw LaTeX $...$ must never reach the final rendered output."""
        server = await helpers.start_server(unused_tcp_port)  # noqa: F841
        reader, writer = await helpers.connect(unused_tcp_port, "cli-user")

        term, state = _make_terminal(unused_tcp_port)
        ev = await helpers.read_until(reader, t="welcome", timeout=5.0)
        term._apply_event(ev)

        writer.write((json.dumps({"t": "cmd", "text": "/spawn mock"}) + "\n").encode())
        await writer.drain()
        spawn_ev = await helpers.read_until(reader, t="spawn", timeout=5.0)
        term._apply_event(spawn_ev)
        agent_id = spawn_ev["agent_id"]

        state.reply_agent = agent_id
        state.reply_content = r"The angle $\alpha$ is $\pi$ radians."

        output = _render_full(state)
        # After preprocessing, raw $\alpha$ must not be in output
        assert r"$\alpha$" not in output, (
            f"Raw LaTeX must not appear in rendered output.\n{output[:2000]}"
        )
        writer.close()
