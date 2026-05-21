"""Visual smoke tests for the MARS renderer — unit tier.

These tests render Rich panels to plain text and assert key strings are present.
No network, no subprocesses, no I/O: pure renderer unit tests.

To regenerate snapshots after an intentional layout change::

    UPDATE_SNAPSHOTS=1 python -m pytest tests/unit/test_renderer_visual.py -v
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from unittest.mock import patch

from mars.client.cli.main import AgentRecord, FeedItem, MARSRenderer, MARSState
from tests.conftest import render_to_text

_FIXED_TS = datetime(2025, 1, 15, 12, 0, 0)


def _patch_now():
    return patch("mars.client.cli.main.datetime", wraps=datetime, **{"now.return_value": _FIXED_TS})


def _render(renderable, *, width: int = 120) -> str:
    return render_to_text(renderable, width=width)


def test_render_sidebar_empty():
    state = MARSState()
    renderer = MARSRenderer(state)
    with _patch_now():
        panel = renderer.render_sidebar()
    text = _render(panel)
    assert "Agents" in text
    assert "No agents yet" in text


def test_render_sidebar_with_agent():
    state = MARSState()
    # Conversational agent (LLMAgent) should appear in sidebar
    state.agents["test-llm@1"] = AgentRecord(agent_id="test-llm@1", agent_type="LLMAgent", fsm_state="IDLE")
    renderer = MARSRenderer(state)
    with _patch_now():
        panel = renderer.render_sidebar()
    text = _render(panel)
    assert "test-llm@1" in text


def test_render_mcp_panel_with_service_agent():
    state = MARSState()
    # ServiceAgent should appear in mcp panel, not sidebar
    state.agents["svc.clock@1"] = AgentRecord(agent_id="svc.clock@1", agent_type="ServiceAgent", fsm_state="IDLE")
    renderer = MARSRenderer(state)
    with _patch_now():
        mcp_text = _render(renderer.render_mcp_panel())
        sidebar_text = _render(renderer.render_sidebar())
    assert "svc.clock@1" in mcp_text, "Service agent must appear in MCP panel"
    assert "svc.clock@1" not in sidebar_text, "Service agent must NOT appear in agents sidebar"


def test_render_mcp_panel_shows_tools():
    """Tools are visible only when the panel is focused and the server is selected."""
    state = MARSState()
    state.agents["svc.github@1"] = AgentRecord(
        agent_id="svc.github@1", agent_type="ServiceAgent",
        tool_schemas=[
            {"name": "search_repos", "description": "Search GitHub repos"},
            {"name": "create_issue", "description": "Create an issue"},
        ],
    )
    renderer = MARSRenderer(state)

    # Collapsed by default (no focus)
    collapsed_text = _render(renderer.render_mcp_panel())
    assert "search_repos" not in collapsed_text
    assert "create_issue" not in collapsed_text
    # Expand indicator should be present
    assert "▶" in collapsed_text

    # Expanded when focused and selected
    state.panel_focus = "mcp"
    state.mcp_cursor = 0
    expanded_text = _render(renderer.render_mcp_panel())
    assert "search_repos" in expanded_text
    assert "create_issue" in expanded_text
    assert "▼" in expanded_text


def test_render_mcp_panel_collapsed_by_default():
    """All servers are collapsed when the panel does not have focus."""
    state = MARSState()
    state.agents["svc.timer@1"] = AgentRecord(
        agent_id="svc.timer@1", agent_type="ServiceAgent",
        tool_schemas=[{"name": "get_time"}, {"name": "geolocate"}],
    )
    state.panel_focus = "chat"  # MCP panel not focused
    renderer = MARSRenderer(state)
    text = _render(renderer.render_mcp_panel())
    # Tools should NOT appear (collapsed)
    assert "get_time" not in text
    assert "geolocate" not in text
    # Expand indicator present
    assert "▶" in text


def test_render_mcp_panel_green_border_when_focused():
    """MCP panel must have green border when it has keyboard focus."""
    state = MARSState()
    state.agents["svc.clock@1"] = AgentRecord(
        agent_id="svc.clock@1", agent_type="ServiceAgent",
    )
    renderer = MARSRenderer(state)

    state.panel_focus = "chat"
    text_unfocused = _render(renderer.render_mcp_panel())

    state.panel_focus = "mcp"
    text_focused = _render(renderer.render_mcp_panel())

    # When focused, cursor indicator ► should appear
    assert "►" in text_focused


def test_render_mcp_panel_cursor_moves():
    """mcp_cursor selects which server is expanded."""
    state = MARSState()
    state.agents["svc.alpha@1"] = AgentRecord(
        agent_id="svc.alpha@1", agent_type="ServiceAgent",
        tool_schemas=[{"name": "tool_a"}],
    )
    state.agents["svc.beta@1"] = AgentRecord(
        agent_id="svc.beta@1", agent_type="ServiceAgent",
        tool_schemas=[{"name": "tool_b"}],
    )
    state.panel_focus = "mcp"
    renderer = MARSRenderer(state)

    # cursor=0 → first server expanded (sorted: svc.alpha@1 < svc.beta@1)
    state.mcp_cursor = 0
    text0 = _render(renderer.render_mcp_panel())
    assert "tool_a" in text0
    assert "tool_b" not in text0

    # cursor=1 → second server expanded
    state.mcp_cursor = 1
    text1 = _render(renderer.render_mcp_panel())
    assert "tool_b" in text1
    assert "tool_a" not in text1


def test_render_connections_empty():
    state = MARSState()
    renderer = MARSRenderer(state)
    text = _render(renderer.render_connections())
    assert "No rooms yet" in text


def test_render_connections_with_room():
    state = MARSState()
    state.rooms["project"] = {"cli-user", "math-agent"}
    renderer = MARSRenderer(state)
    text = _render(renderer.render_connections())
    assert "#project" in text
    assert "math-agent" in text


def test_render_feed_empty_activity():
    state = MARSState()
    renderer = MARSRenderer(state)
    text = _render(renderer.render_feed())
    assert "Activity Feed" in text


def test_render_feed_with_message():
    state = MARSState()
    state.feed = deque([
        FeedItem(ts=_FIXED_TS, event_type="message", from_id="cli-user", to_id="math-agent", snippet="hello")
    ], maxlen=30)
    renderer = MARSRenderer(state)
    text = _render(renderer.render_feed())
    assert "hello" in text
