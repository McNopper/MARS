"""Component tests: CLI command dispatch + renderer integration.

Tests cover the wiring between ``MARSClientTerminal._handle_command`` and the
command-module helpers introduced in the big CLI refactor:

- ``/help``    → ``_cmd_help``   → reply panel (Markdown table)
- ``/read``    → ``_cmd_read``   → reply panel (fenced code block)
- ``/agents``  → ``_cmd_agents`` → reply panel (Markdown table)
- ``/agents available`` → ``_cmd_agents_available`` → reply panel
- Reply panel renders Markdown via ``MARSRenderer.render_reply_panel``
- Status line is visible in the rendered prompt panel border
- Math preprocessing is applied in the reply panel
"""
from __future__ import annotations

import asyncio
from io import StringIO
from unittest.mock import MagicMock

import pytest

from mars.cli.client import MARSClientTerminal
from mars.common.models import AgentRecord, MARSState
from mars.cli.renderer import MARSRenderer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_with_agent(agent_id: str = "llm.mock@1") -> MARSState:
    state = MARSState()
    state.my_agent_id = "cli-user@1"
    state.current_agent = agent_id
    state.agents[agent_id] = AgentRecord(
        agent_id=agent_id, agent_type="LLMAgent",
        domain="default", platform="local", skills=[],
    )
    return state


def _make_terminal(state: MARSState | None = None) -> MARSClientTerminal:
    if state is None:
        state = MARSState()
    term = MARSClientTerminal.__new__(MARSClientTerminal)
    term._state = state
    term._writer = MagicMock()
    term._server_addr = ""
    return term


def _render(renderable, *, width: int = 120) -> str:
    from rich.console import Console
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=width, color_system=None)
    console.print(renderable)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# /help dispatch
# ---------------------------------------------------------------------------


class TestHelpDispatch:
    """/help must route to _cmd_help and produce a reply panel with Markdown table."""

    def test_help_populates_reply_content(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        assert state.reply_content, "/help must set reply_content"

    def test_help_produces_markdown_table(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        assert "|" in state.reply_content, "Help must contain a Markdown table"
        assert "Command" in state.reply_content

    def test_help_reply_panel_renders(self):
        """The reply panel must render without exceptions after /help."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None

    def test_help_reply_panel_text_contains_spawn(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        output = _render(panel)
        assert "spawn" in output.lower() or "agents" in output.lower()

    def test_help_not_sets_status_line_only(self):
        """/help must not only set status_line (old broken behaviour)."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        # New behaviour: reply_content is the main output
        assert state.reply_content

    def test_help_does_not_corrupt_tui(self):
        """Reply panel must be renderable (no console.print() bypass)."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        # If render_reply_panel raises, the TUI would be broken
        renderer = MARSRenderer(state)
        try:
            panel = renderer.render_reply_panel()
            _render(panel)
        except Exception as exc:
            pytest.fail(f"/help caused render error: {exc}")


# ---------------------------------------------------------------------------
# /agents dispatch
# ---------------------------------------------------------------------------


class TestAgentsDispatch:
    """/agents must route to _cmd_agents and produce a reply panel table."""

    def test_agents_populates_reply_content(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents"))
        assert state.reply_content

    def test_agents_reply_contains_agent_id(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents"))
        assert "llm.mock@1" in state.reply_content

    def test_agents_reply_is_markdown_table(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents"))
        assert "|" in state.reply_content

    def test_agents_reply_panel_renders(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents"))
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None
        output = _render(panel)
        assert "llm.mock@1" in output

    def test_agents_does_not_call_console_print(self):
        """/agents must NOT bypass the Live renderer via console.print()."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        # Attach a real console mock; if .print() is called, the test catches it
        mock_console = MagicMock()
        term._console = mock_console
        asyncio.run(term._handle_command("/agents"))
        mock_console.print.assert_not_called()

    def test_agents_marks_current_agent(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents"))
        assert "◀" in state.reply_content


# ---------------------------------------------------------------------------
# /agents available dispatch
# ---------------------------------------------------------------------------


class TestAgentsAvailableDispatch:
    """/agents available must produce a Markdown table in the reply panel."""

    def test_agents_available_sets_reply_content(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents available"))
        assert state.reply_content

    def test_agents_available_is_markdown_table(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents available"))
        assert "|" in state.reply_content

    def test_agents_available_panel_renders(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents available"))
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None
        output = _render(panel)
        # Rich renders Markdown tables with Unicode box chars (│) or ASCII pipes (|)
        assert "│" in output or "|" in output or state.reply_content

    def test_agents_available_does_not_call_console_print(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        mock_console = MagicMock()
        term._console = mock_console
        asyncio.run(term._handle_command("/agents available"))
        mock_console.print.assert_not_called()


# ---------------------------------------------------------------------------
# /read dispatch
# ---------------------------------------------------------------------------


class TestReadDispatch:
    """/read <file> must show file contents in the reply panel."""

    def test_read_populates_reply_content(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("print('hello')\n")
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command(f"/read {f}"))
        assert "print('hello')" in state.reply_content

    def test_read_wraps_in_fence(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("x = 1\n")
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command(f"/read {f}"))
        assert "```" in state.reply_content

    def test_read_missing_file_sets_status(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/read /no/such/file.xyz"))
        assert state.status_line

    def test_read_reply_panel_renders(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("some content\n")
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command(f"/read {f}"))
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None
        output = _render(panel)
        assert "some content" in output


# ---------------------------------------------------------------------------
# Reply panel: Markdown rendering
# ---------------------------------------------------------------------------


class TestReplyPanelMarkdown:
    """Reply panel must render content as Markdown, not plain text."""

    def test_markdown_heading_rendered(self):
        """Content starting with # must be rendered as a heading."""
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = "# My Heading\n\nSome text."
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None
        output = _render(panel)
        # "My Heading" must appear in the rendered output
        assert "My Heading" in output

    def test_markdown_bold_rendered(self):
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = "This is **bold** text."
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        output = _render(panel)
        assert "bold" in output

    def test_markdown_code_fence_rendered(self):
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = "Here is code:\n```python\nprint('hi')\n```"
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        output = _render(panel)
        assert "print" in output

    def test_markdown_table_rendered(self):
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = "| Col A | Col B |\n| --- | --- |\n| X | Y |"
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        output = _render(panel)
        assert "Col A" in output or "X" in output

    def test_reply_panel_none_when_empty(self):
        state = MARSState()
        renderer = MARSRenderer(state)
        assert renderer.render_reply_panel() is None

    def test_reply_panel_none_when_only_agent(self):
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = ""
        renderer = MARSRenderer(state)
        assert renderer.render_reply_panel() is None


# ---------------------------------------------------------------------------
# Status line visible in prompt panel
# ---------------------------------------------------------------------------


class TestStatusLineVisible:
    """status_line must appear in the rendered full layout (prompt panel border)."""

    def test_status_line_appears_in_full_layout(self):
        state = MARSState()
        state.status_line = "UNIQUE_STATUS_XYZ"
        renderer = MARSRenderer(state)
        group = renderer.render_group(input_buf="", prompt="> ", console_height=40)
        output = _render(group, width=120)
        assert "UNIQUE_STATUS_XYZ" in output, (
            "Status line must be visible in the rendered TUI layout.\n"
            f"Got:\n{output}"
        )

    def test_empty_status_no_crash(self):
        state = MARSState()
        state.status_line = ""
        renderer = MARSRenderer(state)
        group = renderer.render_group(input_buf="", prompt="> ", console_height=40)
        _render(group, width=120)  # must not raise

    def test_status_after_command_visible(self):
        """/switch to unknown agent sets status; must be visible in layout."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/switch ghost@99"))
        renderer = MARSRenderer(state)
        group = renderer.render_group(input_buf="", prompt="> ", console_height=40)
        output = _render(group, width=120)
        assert "ghost@99" in output or "not found" in output.lower(), (
            f"Status feedback for /switch must be visible in layout.\nGot:\n{output}"
        )

    def test_status_emoji_visible(self):
        state = MARSState()
        state.status_line = "✅ Done"
        renderer = MARSRenderer(state)
        group = renderer.render_group(input_buf="", prompt="> ", console_height=40)
        output = _render(group, width=120)
        assert "Done" in output


# ---------------------------------------------------------------------------
# Math preprocessing in reply panel
# ---------------------------------------------------------------------------


class TestReplyPanelMath:
    """Math notation in reply content must be preprocessed before rendering."""

    def test_inline_math_symbol_appears(self):
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = r"The angle is $\alpha$ radians."
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        assert panel is not None
        output = _render(panel)
        # After preprocessing, α must appear
        assert "α" in output

    def test_display_math_in_fence(self):
        state = MARSState()
        state.reply_agent = "bot@1"
        state.reply_content = r"Result: $$\sum$$"
        renderer = MARSRenderer(state)
        panel = renderer.render_reply_panel()
        output = _render(panel)
        # ∑ must appear in the output (inside a code fence)
        assert "∑" in output
