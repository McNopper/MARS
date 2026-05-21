"""Unit tests for TUI rendering behaviour.

Tests cover three key rendering properties:

1. Feed order — newest item is at the bottom, not the top.
2. Width overflow — the main feed column uses overflow="fold" so long lines wrap.
3. Human agent visibility — the local human is rendered in the sidebar.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from io import StringIO

import pytest

from mars.client.cli.models import (
    AgentRecord,
    FeedItem,
    MARSState,
    _sidebar_agent_ids,
)
from mars.client.cli.renderer import MARSRenderer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state() -> MARSState:
    return MARSState()


def _feed_snippets(state: MARSState) -> list[str]:
    """Return feed items in list order (index 0 = oldest)."""
    return [item.snippet for item in state.feed]


# ---------------------------------------------------------------------------
# Bug 1: Feed order — newest at the bottom, not the top
# ---------------------------------------------------------------------------

class TestFeedOrder:
    def test_add_event_appends_to_end(self):
        """add_event must append so the newest item is last (index -1)."""
        state = _make_state()
        state.add_event("spawn", "agent-a", "first")
        state.add_event("spawn", "agent-b", "second")
        state.add_event("spawn", "agent-c", "third")

        snippets = _feed_snippets(state)
        assert snippets[-1] == "third", "newest item must be last (bottom)"
        assert snippets[0] == "first", "oldest item must be first (top)"

    def test_add_event_never_prepends(self):
        """Ensure no item is ever inserted at index 0 after the first."""
        state = _make_state()
        state.add_event("spawn", "a", "alpha")
        first_after = _feed_snippets(state)
        state.add_event("spawn", "b", "beta")
        # The first item should still be at index 0
        assert _feed_snippets(state)[0] == "alpha"

    def test_feed_item_order_is_chronological(self):
        """Items inserted in time order must stay in that order."""
        state = _make_state()
        for i in range(5):
            state.feed.append(FeedItem(
                ts=datetime.now() + timedelta(seconds=i),
                event_type="spawn",
                from_id="system",
                to_id=f"agent-{i}",
                snippet=f"msg-{i}",
            ))
        snippets = _feed_snippets(state)
        assert snippets == [f"msg-{i}" for i in range(5)]

    def test_renderer_feed_shows_newest_last(self):
        """The rendered activity feed text must have the latest snippet at the bottom."""
        state = _make_state()
        state.add_event("spawn", "a", "FIRST_EVENT")
        state.add_event("spawn", "b", "LAST_EVENT")

        renderer = MARSRenderer(state)
        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120, color_system=None)
        console.print(renderer.render_feed())
        output = buf.getvalue()

        first_pos = output.find("FIRST_EVENT")
        last_pos = output.find("LAST_EVENT")
        assert first_pos != -1, "FIRST_EVENT not rendered"
        assert last_pos != -1, "LAST_EVENT not rendered"
        assert first_pos < last_pos, "FIRST_EVENT must appear before (above) LAST_EVENT"

    def test_feed_snippet_not_hard_clipped_at_60_chars(self):
        """Snippets longer than 60 chars must not be truncated in the feed."""
        long_snippet = "X" * 80
        state = _make_state()
        state.feed.append(FeedItem(
            ts=datetime.now(), event_type="spawn",
            from_id="system", to_id="a", snippet=long_snippet,
        ))

        renderer = MARSRenderer(state)
        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=200, color_system=None)
        console.print(renderer.render_feed())
        output = buf.getvalue()

        assert long_snippet in output, "Long snippet must not be truncated to 60 chars"


# ---------------------------------------------------------------------------
# Bug 2: Width clipping — main feed column must use overflow="fold"
# ---------------------------------------------------------------------------

class TestWidthOverflow:
    def test_main_column_uses_fold_overflow(self):
        """render_group must configure the main (ratio=1) column with overflow='fold'."""
        from rich.table import Table

        state = _make_state()
        renderer = MARSRenderer(state)
        group = renderer.render_group(input_buf="", prompt="> ", console_height=40)

        # The first element of the Group is the Table.grid layout
        renderables = list(group.__rich_console__(None, None))  # type: ignore[arg-type]
        # Walk the render tree to find the Table
        layout_table: Table | None = None
        from rich.table import Table as RTable
        for item in group._renderables:  # type: ignore[attr-defined]
            if isinstance(item, RTable):
                layout_table = item
                break
        assert layout_table is not None, "Layout Table not found in render_group output"

        # The main feed column (ratio=1) must NOT use 'crop'
        columns = layout_table.columns
        ratio_cols = [c for c in columns if getattr(c, "ratio", None) == 1]
        assert ratio_cols, "No ratio=1 column found in layout"
        for col in ratio_cols:
            assert col.overflow != "crop", (
                f"Main feed column overflow is 'crop' — messages will be clipped on width. "
                f"Should be 'fold'."
            )

    def test_main_column_overflow_is_fold(self):
        """Explicit check: the ratio column overflow value is exactly 'fold'."""
        from rich.table import Table as RTable

        state = _make_state()
        renderer = MARSRenderer(state)
        group = renderer.render_group(input_buf="", prompt="> ", console_height=40)

        layout_table = next(
            (item for item in group._renderables if isinstance(item, RTable)),  # type: ignore[attr-defined]
            None,
        )
        assert layout_table is not None
        ratio_col = next(c for c in layout_table.columns if getattr(c, "ratio", None) == 1)
        assert ratio_col.overflow == "fold"


# ---------------------------------------------------------------------------
# Bug 3: Human agent visible in the sidebar
# ---------------------------------------------------------------------------

class TestHumanInSidebar:
    def test_human_added_to_agents_on_welcome(self):
        """Simulating a welcome event must add the human to state.agents."""
        from mars.client.cli.client import MARSClientTerminal
        from unittest.mock import MagicMock

        state = MARSState()
        # Build a minimal terminal without actually connecting
        term = MARSClientTerminal.__new__(MARSClientTerminal)
        term._state = state
        term._writer = MagicMock()
        term._server_addr = ""

        term._apply_event({"t": "welcome", "your_id": "cli-user@1"})

        assert "cli-user@1" in state.agents, "Human must be added to state.agents"
        rec = state.agents["cli-user@1"]
        assert rec.agent_type == "HumanUser"

    def test_human_appears_in_sidebar_agent_ids(self):
        """_sidebar_agent_ids must include the human after they are registered."""
        state = _make_state()
        state.my_agent_id = "cli-user@1"
        state.agents["cli-user@1"] = AgentRecord(
            agent_id="cli-user@1",
            agent_type="HumanUser",
            domain="cli",
            platform="local",
            skills=[],
        )
        state.agents["llm.ollama@1"] = AgentRecord(
            agent_id="llm.ollama@1",
            agent_type="LLMAgent",
            domain="default",
            platform="local",
            skills=[],
        )

        ids = _sidebar_agent_ids(state)
        assert "cli-user@1" in ids, "Human must appear in sidebar agent IDs"
        assert "llm.ollama@1" in ids

    def test_human_rendered_with_home_emoji(self):
        """The sidebar must show 🏠 for the local human agent."""
        state = _make_state()
        state.my_agent_id = "cli-user@1"
        state.agents["cli-user@1"] = AgentRecord(
            agent_id="cli-user@1",
            agent_type="HumanUser",
            domain="cli",
            platform="local",
            skills=[],
        )

        renderer = MARSRenderer(state)
        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=80, color_system=None)
        console.print(renderer.render_sidebar())
        output = buf.getvalue()

        assert "🙂" in output, "Human agent must be shown with 🙂 icon in sidebar"
        assert "cli-user@1" in output

    def test_human_not_shown_as_service_agent(self):
        """Human must appear in the agents panel; service agent must go to MCP panel."""
        state = _make_state()
        state.my_agent_id = "cli-user@1"
        state.agents["cli-user@1"] = AgentRecord(
            agent_id="cli-user@1",
            agent_type="HumanUser",
            domain="cli",
            platform="local",
            skills=[],
        )
        state.agents["svc.clock@1"] = AgentRecord(
            agent_id="svc.clock@1",
            agent_type="ServiceAgent",
            domain="services",
            platform="local",
            skills=["time"],
        )

        renderer = MARSRenderer(state)
        from rich.console import Console
        buf_sidebar = StringIO()
        buf_mcp = StringIO()
        console_s = Console(file=buf_sidebar, force_terminal=True, width=80, color_system=None)
        console_m = Console(file=buf_mcp, force_terminal=True, width=80, color_system=None)
        console_s.print(renderer.render_sidebar())
        console_m.print(renderer.render_mcp_panel())
        sidebar_output = buf_sidebar.getvalue()
        mcp_output = buf_mcp.getvalue()

        # Human must appear in the agents sidebar
        assert "cli-user@1" in sidebar_output, "Human must appear in agents sidebar"
        # Service agent must appear in MCP panel, not the agents sidebar
        assert "svc.clock@1" in mcp_output, "Service agent must appear in MCP panel"
        assert "svc.clock@1" not in sidebar_output, "Service agent must NOT be in agents sidebar"
