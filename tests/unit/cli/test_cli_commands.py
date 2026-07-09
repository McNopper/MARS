"""Unit tests for CLI command helpers and local command handling.

Tests cover:
- ``_expand_file_mentions``    — @path token expansion
- ``_handle_bang_cmd``         — !cmd shell shortcut
- ``_cmd_new``                 — clear conversation history
- ``_cmd_rewind``              — remove last message pair
- ``_cmd_context``             — token usage estimate
- ``_cmd_share``               — export to markdown file
- ``_cmd_search``              — search conversation history
- ``_cmd_version``             — show installed version
- ``_cmd_copy``                — copy last reply
- ``MARSClientTerminal._handle_command``   — local command dispatch
- ``MARSClientTerminal._apply_event``      — server-event application
- Thinking spinner             — THINKING dot appears in the sidebar ASCII render
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock


from mars.cli.client import MARSClientTerminal
from mars.cli.main import (
    _cmd_context,
    _cmd_new,
    _cmd_rewind,
    _cmd_search,
    _cmd_share,
    _cmd_version,
    _expand_file_mentions,
    _handle_bang_cmd,
)
from mars.common.models import (
    AgentRecord,
    ChatMessage,
    MARSState,
)
from mars.cli.renderer import MARSRenderer


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_state_with_agent(agent_id: str = "llm.mock@1") -> MARSState:
    state = MARSState()
    state.my_agent_id = "cli-user@1"
    state.current_agent = agent_id
    state.agents[agent_id] = AgentRecord(
        agent_id=agent_id,
        agent_type="LLMAgent",
        domain="default",
        platform="local",
        skills=[],
    )
    return state


def _make_terminal(state: MARSState | None = None) -> MARSClientTerminal:
    """Build a MARSClientTerminal without a real TCP connection."""
    if state is None:
        state = MARSState()
    term = MARSClientTerminal.__new__(MARSClientTerminal)
    term._state = state
    term._writer = MagicMock()
    term._server_addr = ""
    return term


def _render_services(state: MARSState, width: int = 40) -> str:
    """Render services panel to plain ASCII string."""
    from rich.console import Console
    renderer = MARSRenderer(state)
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=width, color_system=None)
    console.print(renderer.render_services())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _expand_file_mentions
# ---------------------------------------------------------------------------


class TestExpandFileMentions:
    def test_replaces_at_path_with_file_content(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        result = _expand_file_mentions(f"Look at @{f}")
        assert "print('hello')" in result

    def test_wraps_content_in_code_fence(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        result = _expand_file_mentions(f"@{f}")
        assert "```py" in result

    def test_leaves_missing_path_verbatim(self):
        result = _expand_file_mentions("@/no/such/file.py")
        assert result == "@/no/such/file.py"

    def test_multiple_at_tokens(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("AAA")
        b.write_text("BBB")
        result = _expand_file_mentions(f"@{a} and @{b}")
        assert "AAA" in result
        assert "BBB" in result


# ---------------------------------------------------------------------------
# _handle_bang_cmd
# ---------------------------------------------------------------------------


class TestHandleBangCmd:
    def test_returns_false_for_non_bang(self):
        assert _handle_bang_cmd("hello world") is False

    def test_returns_true_for_bang_prefix(self, capsys):
        handled = _handle_bang_cmd("!echo bang_test")
        assert handled is True
        out = capsys.readouterr().out
        assert "bang_test" in out

    def test_empty_bang_returns_true_without_running(self):
        assert _handle_bang_cmd("!") is True

    def test_command_output_printed(self, capsys):
        _handle_bang_cmd("!echo HELLO_FROM_BANG")
        out = capsys.readouterr().out
        assert "HELLO_FROM_BANG" in out


# ---------------------------------------------------------------------------
# _cmd_new
# ---------------------------------------------------------------------------


class TestCmdNew:
    def test_clears_agent_chat(self):
        state = _make_state_with_agent()
        state.agents["llm.mock@1"].chat.append(
            ChatMessage(ts=datetime.now(), sender="llm.mock@1", content="hi", direction="in")
        )
        _cmd_new(state)
        assert len(state.agents["llm.mock@1"].chat) == 0

    def test_clears_feed(self):
        state = _make_state_with_agent()
        state.add_event("spawn", "a", "test")
        _cmd_new(state)
        assert len(state.feed) == 0

    def test_sets_status_message(self):
        state = _make_state_with_agent()
        _cmd_new(state)
        assert "cleared" in state.status_line.lower() or "new" in state.status_line.lower()

    def test_clears_reply_content(self):
        state = _make_state_with_agent()
        state.reply_content = "some reply"
        _cmd_new(state)
        assert state.reply_content == ""


# ---------------------------------------------------------------------------
# _cmd_rewind
# ---------------------------------------------------------------------------


class TestCmdRewind:
    def test_removes_last_two_messages(self):
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        for i in range(4):
            rec.chat.append(ChatMessage(ts=datetime.now(), sender="x", content=f"msg{i}", direction="out"))
        _cmd_rewind(state)
        assert len(rec.chat) == 2
        assert list(rec.chat)[0].content == "msg0"
        assert list(rec.chat)[1].content == "msg1"

    def test_rewind_empty_chat_does_not_fail(self):
        state = _make_state_with_agent()
        _cmd_rewind(state)
        # Status message is set regardless (e.g. "Rewound 0 message(s).")
        assert state.status_line

    def test_rewind_sets_status_message(self):
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="x", content="a", direction="out"))
        _cmd_rewind(state)
        assert state.status_line  # non-empty status


# ---------------------------------------------------------------------------
# _cmd_context
# ---------------------------------------------------------------------------


class TestCmdContext:
    def test_shows_token_estimate(self):
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="x", content="hello world", direction="in"))
        _cmd_context(state)
        assert "token" in state.status_line.lower()

    def test_counts_messages(self):
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        for i in range(3):
            rec.chat.append(ChatMessage(ts=datetime.now(), sender="x", content="x" * 100, direction="in"))
        _cmd_context(state)
        assert "3" in state.status_line

    def test_no_agent_shows_zero(self):
        state = MARSState()
        _cmd_context(state)
        assert "0" in state.status_line


# ---------------------------------------------------------------------------
# _cmd_share
# ---------------------------------------------------------------------------


class TestCmdShare:
    def test_creates_markdown_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="user", content="hello", direction="out"))
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="llm.mock@1", content="hi there", direction="in"))
        _cmd_share(state, "test-session.md")
        assert (tmp_path / "test-session.md").exists()

    def test_file_contains_messages(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="user", content="UNIQUE_USER_MSG", direction="out"))
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="llm.mock@1", content="UNIQUE_AGENT_REPLY", direction="in"))
        _cmd_share(state, "out.md")
        content = (tmp_path / "out.md").read_text()
        assert "UNIQUE_USER_MSG" in content
        assert "UNIQUE_AGENT_REPLY" in content

    def test_sets_status_message(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state = _make_state_with_agent()
        _cmd_share(state, "share.md")
        assert "share.md" in state.status_line or "exported" in state.status_line.lower()


# ---------------------------------------------------------------------------
# _cmd_search
# ---------------------------------------------------------------------------


class TestCmdSearch:
    def test_finds_matching_messages(self):
        state = _make_state_with_agent()
        rec = state.agents["llm.mock@1"]
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="x", content="the rain in spain", direction="in"))
        rec.chat.append(ChatMessage(ts=datetime.now(), sender="x", content="unrelated content", direction="in"))
        _cmd_search(state, "rain")
        assert "rain" in state.reply_content

    def test_no_match_sets_status(self):
        state = _make_state_with_agent()
        _cmd_search(state, "zzznomatch")
        assert "no match" in state.status_line.lower() or "zzznomatch" in state.status_line

    def test_empty_query_shows_usage(self):
        state = _make_state_with_agent()
        _cmd_search(state, "")
        assert "usage" in state.status_line.lower() or "search" in state.status_line.lower()

    def test_no_agent_shows_status(self):
        state = MARSState()
        _cmd_search(state, "anything")
        assert state.status_line


# ---------------------------------------------------------------------------
# _cmd_version
# ---------------------------------------------------------------------------


class TestCmdVersion:
    def test_sets_version_in_status(self):
        state = MARSState()
        _cmd_version(state)
        assert "mars" in state.status_line.lower() or "v" in state.status_line.lower()

# ---------------------------------------------------------------------------
# MARSClientTerminal._apply_event
# ---------------------------------------------------------------------------


class TestApplyEvent:
    def test_welcome_sets_my_agent_id(self):
        term = _make_terminal()
        term._apply_event({"t": "welcome", "your_id": "cli-user@3"})
        assert term._state.my_agent_id == "cli-user@3"

    def test_welcome_registers_human_in_agents(self):
        term = _make_terminal()
        term._apply_event({"t": "welcome", "your_id": "cli-user@3"})
        assert "cli-user@3" in term._state.agents

    def test_spawn_adds_agent(self):
        term = _make_terminal()
        term._apply_event({
            "t": "spawn", "agent_id": "llm.mock@1",
            "agent_type": "LLMAgent", "domain": "default",
        })
        assert "llm.mock@1" in term._state.agents

    def test_spawn_auto_selects_first_llm(self):
        term = _make_terminal()
        term._apply_event({"t": "welcome", "your_id": "cli-user@1"})
        term._apply_event({
            "t": "spawn", "agent_id": "llm.mock@1",
            "agent_type": "LLMAgent", "domain": "default",
        })
        assert term._state.current_agent == "llm.mock@1"

    def test_despawn_removes_agent(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        term._apply_event({"t": "despawn", "agent_id": "llm.mock@1"})
        assert "llm.mock@1" not in term._state.agents

    def test_fsm_event_updates_state(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        term._apply_event({"t": "fsm", "agent_id": "llm.mock@1", "fsm_state": "THINKING"})
        assert term._state.agents["llm.mock@1"].fsm_state == "THINKING"

    def test_chat_event_adds_message(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        term._apply_event({
            "t": "chat", "agent_id": "llm.mock@1",
            "ts": datetime.now().isoformat(),
            "sender": "llm.mock@1",
            "content": "Hello from agent",
            "direction": "in",
        })
        messages = list(state.agents["llm.mock@1"].chat)
        assert any("Hello from agent" in m.content for m in messages)

    def test_chat_event_appears_in_history(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        term._apply_event({
            "t": "chat", "agent_id": "llm.mock@1",
            "ts": datetime.now().isoformat(),
            "sender": "llm.mock@1",
            "content": "A reply",
            "direction": "in",
        })
        assert any("A reply" in m.content for m in state.agents["llm.mock@1"].chat)

    def test_status_event_sets_status_line(self):
        term = _make_terminal()
        term._apply_event({"t": "status", "text": "test-status-xyz", "style": ""})
        assert term._state.status_line == "test-status-xyz"

    def test_feed_event_adds_to_feed(self):
        term = _make_terminal()
        term._apply_event({
            "t": "feed", "event_type": "system",
            "from_id": "server", "to_id": "",
            "snippet": "FEED_CONTENT_XYZ",
            "ts": datetime.now().isoformat(),
        })
        snippets = [item.snippet for item in term._state.feed]
        assert any("FEED_CONTENT_XYZ" in s for s in snippets)

    def test_switch_event_changes_current_agent(self):
        state = _make_state_with_agent("llm.mock@1")
        state.agents["llm.other@1"] = AgentRecord(
            agent_id="llm.other@1", agent_type="LLMAgent",
            domain="default", platform="local", skills=[],
        )
        term = _make_terminal(state)
        term._apply_event({"t": "switch", "current_agent": "#llm.other@1"})
        assert term._state.current_agent == "llm.other@1"


# ---------------------------------------------------------------------------
# Local command dispatch (_handle_command)
# ---------------------------------------------------------------------------


class TestHandleCommandLocal:
    def test_quit_returns_true(self):
        term = _make_terminal()
        result = asyncio.run(term._handle_command("/quit"))
        assert result is True

    def test_switch_to_known_agent(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/switch llm.mock@1"))
        assert state.current_agent == "llm.mock@1"

    def test_switch_to_unknown_agent_sets_status(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/switch nobody@99"))
        assert "not found" in state.status_line.lower()

    def test_switch_no_arg_shows_usage(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/switch"))
        assert "usage" in state.status_line.lower()

    def test_echo_sets_mode(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/echo md"))
        assert state.echo_mode == "md"

    def test_echo_invalid_mode_shows_error(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/echo bogusmode"))
        assert "unknown" in state.status_line.lower()

    def test_verbose_toggles_agent(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/verbose llm.mock@1"))
        assert state.agents["llm.mock@1"].verbose is True
        asyncio.run(term._handle_command("/verbose llm.mock@1"))
        assert state.agents["llm.mock@1"].verbose is False

    def test_new_clears_chat_history(self):
        state = _make_state_with_agent()
        state.agents["llm.mock@1"].chat.append(
            __import__("mars.common.models", fromlist=["ChatMessage"]).ChatMessage(
                ts=__import__("datetime").datetime.now(),
                sender="llm.mock@1", content="old msg", direction="in",
            )
        )
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/new"))
        assert len(state.agents["llm.mock@1"].chat) == 0

    def test_status_command_formats_fsm(self):
        state = _make_state_with_agent()
        state.agents["llm.mock@1"].fsm_state = "IDLE"
        state.agents["llm.mock@1"].fsm_strategy = "reactive"
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/status llm.mock@1"))
        assert "IDLE" in state.status_line
        assert "reactive" in state.status_line

    def test_unknown_command_forwarded_to_server(self):
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/spawn mock"))
        term._writer.write.assert_called_once()
        payload = json.loads(term._writer.write.call_args[0][0].decode().strip())
        assert payload["t"] == "cmd"
        assert "/spawn mock" in payload["text"]

    def test_help_sets_reply_content(self):
        """/help must populate reply_content with a Markdown command table."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        assert state.reply_content, "/help must set reply_content"
        assert "|" in state.reply_content or "/" in state.reply_content, (
            "reply_content must contain command reference"
        )


# ---------------------------------------------------------------------------
# Agent state display is now handled in other panels (connections/feed)
# Services panel shows available services, not active agent states
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _require_agent helper
# ---------------------------------------------------------------------------


class TestRequireAgent:
    def test_returns_agent_id_when_valid(self):
        from mars.cli.commands import _require_agent
        state = _make_state_with_agent()
        result = _require_agent(state)
        assert result == "llm.mock@1"

    def test_returns_none_when_no_agent(self):
        from mars.cli.commands import _require_agent
        state = MARSState()
        assert _require_agent(state) is None

    def test_sets_status_line_when_no_agent(self):
        from mars.cli.commands import _require_agent
        state = MARSState()
        _require_agent(state)
        assert state.status_line  # non-empty

    def test_returns_none_for_unknown_current_agent(self):
        from mars.cli.commands import _require_agent
        state = MARSState()
        state.current_agent = "ghost@99"  # not in state.agents
        assert _require_agent(state) is None


# ---------------------------------------------------------------------------
# _reply helper
# ---------------------------------------------------------------------------


class TestReplyHelper:
    def test_sets_reply_agent(self):
        from mars.cli.commands import _reply
        state = MARSState()
        _reply(state, "bot@1", "Hello!")
        assert state.reply_agent == "bot@1"

    def test_sets_reply_content(self):
        from mars.cli.commands import _reply
        state = MARSState()
        _reply(state, "bot@1", "Some content")
        assert state.reply_content == "Some content"


# ---------------------------------------------------------------------------
# _send_msg helper
# ---------------------------------------------------------------------------


class TestSendMsg:
    def test_writes_json_frame(self):
        from mars.cli.commands import _send_msg
        writer = MagicMock()
        _send_msg(writer, "llm.mock@1", "hello")
        writer.write.assert_called_once()
        payload = json.loads(writer.write.call_args[0][0].decode().strip())
        assert payload["t"] == "msg"
        assert payload["target"] == "llm.mock@1"
        assert payload["text"] == "hello"


# ---------------------------------------------------------------------------
# _cmd_help
# ---------------------------------------------------------------------------


class TestCmdHelp:
    def test_sets_reply_content(self):
        from mars.cli.commands import _cmd_help
        state = MARSState()
        _cmd_help(state)
        assert state.reply_content

    def test_reply_content_is_markdown_table(self):
        from mars.cli.commands import _cmd_help
        state = MARSState()
        _cmd_help(state)
        # Help text must include a Markdown table header row
        assert "|" in state.reply_content
        assert "Command" in state.reply_content

    def test_contains_common_commands(self):
        from mars.cli.commands import _cmd_help
        state = MARSState()
        _cmd_help(state)
        for cmd in ("/spawn", "/agents", "/help", "/quit", "/echo"):
            assert cmd in state.reply_content, f"{cmd} must be in help text"

    def test_reply_agent_set(self):
        from mars.cli.commands import _cmd_help
        state = MARSState()
        _cmd_help(state)
        assert state.reply_agent  # must be attributed to some agent string

    def test_via_handle_command(self):
        """_handle_command('/help') must route to _cmd_help (reply panel, not status)."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/help"))
        assert state.reply_content, "/help must populate reply_content"
        assert "|" in state.reply_content, "/help must produce a Markdown table"


# ---------------------------------------------------------------------------
# _cmd_agents
# ---------------------------------------------------------------------------


class TestCmdAgents:
    def test_with_agents_sets_reply_content(self):
        from mars.cli.commands import _cmd_agents
        state = _make_state_with_agent()
        _cmd_agents(state)
        assert state.reply_content

    def test_reply_content_contains_agent_id(self):
        from mars.cli.commands import _cmd_agents
        state = _make_state_with_agent()
        _cmd_agents(state)
        assert "llm.mock@1" in state.reply_content

    def test_reply_content_is_markdown_table(self):
        from mars.cli.commands import _cmd_agents
        state = _make_state_with_agent()
        _cmd_agents(state)
        assert "|" in state.reply_content

    def test_current_agent_marked(self):
        from mars.cli.commands import _cmd_agents
        state = _make_state_with_agent()
        _cmd_agents(state)
        assert "◀" in state.reply_content

    def test_no_agents_sets_status(self):
        from mars.cli.commands import _cmd_agents
        state = MARSState()
        _cmd_agents(state)
        assert state.status_line  # error feedback when empty

    def test_via_handle_command(self):
        """_handle_command('/agents') must populate reply panel, not corrupt TUI."""
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command("/agents"))
        assert state.reply_content, "/agents must populate reply_content"
        assert "llm.mock@1" in state.reply_content


# ---------------------------------------------------------------------------
# _cmd_read
# ---------------------------------------------------------------------------


class TestCmdRead:
    def test_reads_existing_file(self, tmp_path):
        from mars.cli.commands import _cmd_read
        f = tmp_path / "notes.txt"
        f.write_text("line1\nline2\n")
        state = MARSState()
        _cmd_read(state, str(f))
        assert "line1" in state.reply_content
        assert "line2" in state.reply_content

    def test_file_wrapped_in_fence(self, tmp_path):
        from mars.cli.commands import _cmd_read
        f = tmp_path / "sample.py"
        f.write_text("x = 1\n")
        state = MARSState()
        _cmd_read(state, str(f))
        assert "```" in state.reply_content

    def test_missing_file_sets_status(self):
        from mars.cli.commands import _cmd_read
        state = MARSState()
        _cmd_read(state, "/no/such/file.txt")
        assert state.status_line
        assert not state.reply_content

    def test_empty_path_sets_status(self):
        from mars.cli.commands import _cmd_read
        state = MARSState()
        _cmd_read(state, "")
        assert "usage" in state.status_line.lower() or "read" in state.status_line.lower()

    def test_reply_agent_is_filename(self, tmp_path):
        from mars.cli.commands import _cmd_read
        f = tmp_path / "readme.md"
        f.write_text("# readme\n")
        state = MARSState()
        _cmd_read(state, str(f))
        assert "readme.md" in state.reply_agent

    def test_via_handle_command(self, tmp_path):
        """/read <file> via _handle_command must work end-to-end."""
        f = tmp_path / "data.txt"
        f.write_text("FILEDATA_XYZ\n")
        state = _make_state_with_agent()
        term = _make_terminal(state)
        asyncio.run(term._handle_command(f"/read {f}"))
        assert "FILEDATA_XYZ" in state.reply_content

    def test_directory_sets_status(self, tmp_path):
        from mars.cli.commands import _cmd_read
        state = MARSState()
        _cmd_read(state, str(tmp_path))
        assert state.status_line  # must report error for directory input


# ---------------------------------------------------------------------------
# _handle_bang_cmd — state routing (TUI mode)
# ---------------------------------------------------------------------------


class TestHandleBangCmdTUIMode:
    def test_state_receives_output_in_tui_mode(self):
        state = MARSState()
        from mars.cli.commands import _handle_bang_cmd
        _handle_bang_cmd("!echo TUI_TEST_OUTPUT", state)
        assert "TUI_TEST_OUTPUT" in state.reply_content

    def test_reply_agent_set_to_shell(self):
        state = MARSState()
        from mars.cli.commands import _handle_bang_cmd
        _handle_bang_cmd("!echo hi", state)
        assert "shell" in state.reply_agent.lower()
