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

from mars.cli.main import AgentRecord, FeedItem, MARSRenderer, MARSState
from tests.conftest import render_to_text

_FIXED_TS = datetime(2025, 1, 15, 12, 0, 0)


def _patch_now():
    return patch("mars.cli.main.datetime", wraps=datetime, **{"now.return_value": _FIXED_TS})


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
    state.agents["test-agent"] = AgentRecord(agent_id="test-agent", agent_type="ServiceAgent", fsm_state="IDLE")
    renderer = MARSRenderer(state)
    with _patch_now():
        panel = renderer.render_sidebar()
    text = _render(panel)
    assert "test-agent" in text


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
