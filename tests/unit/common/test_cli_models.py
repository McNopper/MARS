"""Unit tests for mars.common.models and mars.cli.nav."""
from __future__ import annotations

from collections import deque
from datetime import datetime

from mars.common.models import (
    AGENT_EMOJIS,
    AgentRecord,
    ChatMessage,
    FeedItem,
    MARSState,
)
from mars.cli.nav import (
    _is_conversational,
    _mcp_agent_ids,
    _nav_connections,
    _nav_mcp,
    _nav_sidebar,
    _sidebar_agent_ids,
    _sync_sidebar_cursor,
)


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------


class TestChatMessage:
    def test_defaults(self) -> None:
        msg = ChatMessage(sender="a.1", content="hello", ts=datetime.now())
        assert msg.sender == "a.1"
        assert msg.content == "hello"

    def test_direction_default_is_out(self) -> None:
        msg = ChatMessage(sender="bot.1", content="x", ts=datetime.now())
        assert msg.direction == "out"

    def test_custom_direction(self) -> None:
        msg = ChatMessage(sender="bot.1", content="reply", ts=datetime.now(), direction="in")
        assert msg.direction == "in"


# ---------------------------------------------------------------------------
# AgentRecord
# ---------------------------------------------------------------------------


class TestAgentRecord:
    def test_defaults(self) -> None:
        rec = AgentRecord(agent_id="bot.1")
        assert rec.agent_type == "Agent"
        assert rec.domain == "default"
        assert not rec.is_current
        assert rec.status == "active"
        assert isinstance(rec.chat, deque)

    def test_has_reply_default_false(self) -> None:
        rec = AgentRecord(agent_id="bot.1")
        assert not rec.has_reply

    def test_verbose_default_false(self) -> None:
        rec = AgentRecord(agent_id="bot.1")
        assert not rec.verbose

    def test_competence_defaults(self) -> None:
        rec = AgentRecord(agent_id="bot.1")
        assert rec.competence_level == "COMPETENT"
        assert rec.competence_score == 50.0


# ---------------------------------------------------------------------------
# FeedItem
# ---------------------------------------------------------------------------


class TestFeedItem:
    def test_creation(self) -> None:
        item = FeedItem(
            ts=datetime.now(),
            event_type="spawn",
            from_id="system",
            to_id="bot.1",
            snippet="bot.1 spawned",
        )
        assert item.event_type == "spawn"
        assert item.performative == "INFORM"


# ---------------------------------------------------------------------------
# AGENT_EMOJIS
# ---------------------------------------------------------------------------


class TestAgentEmojis:
    def test_llm_agent_has_emoji(self) -> None:
        assert "LLMAgent" in AGENT_EMOJIS

    def test_provider_has_emoji(self) -> None:
        assert "Provider" in AGENT_EMOJIS


# ---------------------------------------------------------------------------
# MARSState
# ---------------------------------------------------------------------------


class TestMARSState:
    def test_empty_on_creation(self) -> None:
        state = MARSState()
        assert state.agents == {}
        assert state.current_agent is None
        assert len(state.feed) == 0

    def test_add_event_appends_to_feed(self) -> None:
        state = MARSState()
        state.add_event("spawn", "bot.1", "bot spawned")
        assert len(state.feed) == 1
        item = state.feed[0]
        assert item.event_type == "spawn"
        assert item.to_id == "bot.1"

    def test_fire_calls_listeners(self) -> None:
        state = MARSState()
        events = []
        state._event_listeners.append(lambda ev: events.append(ev))
        state._fire({"t": "test"})
        assert len(events) == 1
        assert events[0]["t"] == "test"

    def test_fire_ignores_failing_listener(self) -> None:
        state = MARSState()

        def bad_listener(ev):
            raise RuntimeError("boom")

        state._event_listeners.append(bad_listener)
        # Should not raise
        state._fire({"t": "test"})

    def test_emoji_unknown_agent_returns_default(self) -> None:
        state = MARSState()
        assert state.emoji("nobody.1") == "👤"

    def test_emoji_llm_agent(self) -> None:
        state = MARSState()
        state.agents["bot.1"] = AgentRecord(agent_id="bot.1", agent_type="LLMAgent")
        emoji = state.emoji("bot.1")
        assert emoji == AGENT_EMOJIS["LLMAgent"]

    def test_emoji_human_with_custom_avatar(self) -> None:
        state = MARSState()
        state.agents["user.1"] = AgentRecord(
            agent_id="user.1", agent_type="HumanUser", avatar="🧑"
        )
        assert state.emoji("user.1") == "🧑"

    def test_emoji_llm_agent_ignores_custom_avatar(self) -> None:
        state = MARSState()
        state.agents["bot.1"] = AgentRecord(
            agent_id="bot.1", agent_type="LLMAgent", avatar="🚀"
        )
        # LLM agents always use their type emoji, not avatar
        assert state.emoji("bot.1") == AGENT_EMOJIS["LLMAgent"]


# ---------------------------------------------------------------------------
# _is_conversational
# ---------------------------------------------------------------------------


class TestIsConversational:
    def test_llm_agent_is_conversational(self) -> None:
        rec = AgentRecord(agent_id="bot.1", agent_type="LLMAgent")
        assert _is_conversational(rec)

    def test_human_user_is_conversational(self) -> None:
        rec = AgentRecord(agent_id="user.1", agent_type="HumanUser")
        assert _is_conversational(rec)

    def test_provider_is_not_conversational(self) -> None:
        rec = AgentRecord(agent_id="svc.1", agent_type="Provider")
        assert not _is_conversational(rec)

    def test_echo_bot_is_not_conversational(self) -> None:
        rec = AgentRecord(agent_id="echo.1", agent_type="EchoBot")
        assert not _is_conversational(rec)


# ---------------------------------------------------------------------------
# _sidebar_agent_ids
# ---------------------------------------------------------------------------


class TestSidebarAgentIds:
    def _make_state(self) -> MARSState:
        state = MARSState()
        state.agents["llm.1"] = AgentRecord(agent_id="llm.1", agent_type="LLMAgent")
        state.agents["svc.1"] = AgentRecord(agent_id="svc.1", agent_type="Provider")
        state.agents["user.1"] = AgentRecord(agent_id="user.1", agent_type="HumanUser")
        return state

    def test_only_conversational_agents_returned(self) -> None:
        state = self._make_state()
        ids = _sidebar_agent_ids(state)
        assert "llm.1" in ids
        assert "user.1" in ids
        assert "svc.1" not in ids

    def test_empty_state_returns_empty(self) -> None:
        state = MARSState()
        assert _sidebar_agent_ids(state) == []


# ---------------------------------------------------------------------------
# _nav_sidebar
# ---------------------------------------------------------------------------


class TestNavSidebar:
    def _state_with_agents(self) -> MARSState:
        state = MARSState()
        for i in range(1, 4):
            state.agents[f"bot.{i}"] = AgentRecord(
                agent_id=f"bot.{i}", agent_type="LLMAgent"
            )
        state.sidebar_cursor = 0
        state.sidebar_scroll = 0
        state.sidebar_visible_height = 10
        # _nav_sidebar uses a hierarchical tree (server → category → item).
        # Expand "local" server and its "unknown" vendor-category so all agent
        # rows are visible and navigable.
        state.sidebar_servers_expand["local"] = True
        state.sidebar_categories_expand["local:unknown"] = True
        return state

    def test_nav_down_moves_cursor(self) -> None:
        state = self._state_with_agents()
        _nav_sidebar(state, 1)
        # Row 0 = server "local", row 1 = category "unknown" — cursor moves to 1.
        assert state.sidebar_cursor == 1

    def test_nav_up_clamps_at_zero(self) -> None:
        state = self._state_with_agents()
        _nav_sidebar(state, -5)
        assert state.sidebar_cursor == 0

    def test_nav_down_clamps_at_last(self) -> None:
        state = self._state_with_agents()
        _nav_sidebar(state, 100)
        # Hierarchy rows: server(1) + category(1) + 3 agents = 5 rows; last index = 4.
        assert state.sidebar_cursor == 4

    def test_nav_leaves_current_agent_unchanged(self) -> None:
        state = self._state_with_agents()
        state.current_agent = "bot.1"
        _nav_sidebar(state, 1)
        assert state.current_agent == "bot.1"

    def test_nav_advances_through_hierarchy_rows(self) -> None:
        """Cursor moves through server → category → item rows step by step."""
        state = self._state_with_agents()
        assert state.sidebar_cursor == 0          # server row
        _nav_sidebar(state, 1)
        assert state.sidebar_cursor == 1          # category row
        _nav_sidebar(state, 1)
        assert state.sidebar_cursor == 2          # first agent row

    def test_nav_empty_state_is_noop(self) -> None:
        state = MARSState()
        _nav_sidebar(state, 1)  # Should not raise


# ---------------------------------------------------------------------------
# _sync_sidebar_cursor
# ---------------------------------------------------------------------------


class TestConnectionsNav:
    def test_nav_sets_current_agent(self) -> None:
        state = MARSState()
        # _nav_connections navigates agent↔partner pairs, not state.rooms.
        # Seed one HumanUser (the CLI's own agent) and one LLMAgent partner.
        state.my_agent_id = "user@1"
        state.agents["user@1"] = AgentRecord(agent_id="user@1", agent_type="HumanUser")
        state.agents["beta"] = AgentRecord(agent_id="beta", agent_type="LLMAgent")
        _nav_connections(state, 1)
        # items: [("user@1", True), ("beta", False)]; cursor 1 → partner "beta"
        assert state.current_agent == "beta"
        assert state.connections_cursor == 1


class TestSyncSidebarCursor:
    def test_sync_sets_cursor_to_current_agent(self) -> None:
        state = MARSState()
        for i in range(1, 4):
            state.agents[f"bot.{i}"] = AgentRecord(
                agent_id=f"bot.{i}", agent_type="LLMAgent"
            )
        ids = _sidebar_agent_ids(state)
        state.current_agent = ids[2]
        state.sidebar_cursor = 0
        _sync_sidebar_cursor(state)
        assert state.sidebar_cursor == 2

    def test_sync_no_match_leaves_cursor_unchanged(self) -> None:
        state = MARSState()
        state.current_agent = "ghost.1"
        state.sidebar_cursor = 5
        _sync_sidebar_cursor(state)
        assert state.sidebar_cursor == 5


# ---------------------------------------------------------------------------
# _mcp_agent_ids
# ---------------------------------------------------------------------------


class TestMCPAgentIds:
    def test_returns_only_service_agents(self) -> None:
        state = MARSState()
        state.agents["llm.1"] = AgentRecord(agent_id="llm.1", agent_type="LLMAgent")
        state.agents["svc.1"] = AgentRecord(agent_id="svc.1", agent_type="Provider")
        ids = _mcp_agent_ids(state)
        assert "svc.1" in ids
        assert "llm.1" not in ids

    def test_excludes_echo_bots(self) -> None:
        state = MARSState()
        state.agents["echo-text"] = AgentRecord(agent_id="echo-text", agent_type="EchoBot")
        state.agents["svc.1"] = AgentRecord(agent_id="svc.1", agent_type="Provider")
        ids = _mcp_agent_ids(state)
        assert "echo-text" not in ids
        assert "svc.1" in ids

    def test_returns_sorted(self) -> None:
        state = MARSState()
        state.agents["svc.z"] = AgentRecord(agent_id="svc.z", agent_type="Provider")
        state.agents["svc.a"] = AgentRecord(agent_id="svc.a", agent_type="Provider")
        ids = _mcp_agent_ids(state)
        assert ids == sorted(ids)

    def test_empty_state_returns_empty(self) -> None:
        assert _mcp_agent_ids(MARSState()) == []


# ---------------------------------------------------------------------------
# _nav_mcp
# ---------------------------------------------------------------------------


class TestNavMCP:
    def _state_with_services(self) -> MARSState:
        state = MARSState()
        for name in ["svc.alpha", "svc.beta", "svc.gamma"]:
            state.agents[name] = AgentRecord(agent_id=name, agent_type="Provider")
        state.mcp_cursor = 0
        state.mcp_scroll = 0
        state.mcp_visible_height = 10
        return state

    def test_nav_down_moves_cursor(self) -> None:
        state = self._state_with_services()
        _nav_mcp(state, 1)
        assert state.mcp_cursor == 1

    def test_nav_up_clamps_at_zero(self) -> None:
        state = self._state_with_services()
        _nav_mcp(state, -5)
        assert state.mcp_cursor == 0

    def test_nav_down_clamps_at_last(self) -> None:
        state = self._state_with_services()
        _nav_mcp(state, 100)
        ids = _mcp_agent_ids(state)
        assert state.mcp_cursor == len(ids) - 1

    def test_scroll_follows_cursor_down(self) -> None:
        state = self._state_with_services()
        state.mcp_visible_height = 2   # only 2 visible at a time
        state.mcp_cursor = 0
        _nav_mcp(state, 2)             # cursor → 2, beyond window
        assert state.mcp_scroll >= 1  # scroll must have advanced

    def test_scroll_follows_cursor_up(self) -> None:
        state = self._state_with_services()
        state.mcp_visible_height = 2
        state.mcp_cursor = 2
        state.mcp_scroll = 2
        _nav_mcp(state, -2)            # cursor → 0, before window
        assert state.mcp_scroll == 0

    def test_nav_empty_state_is_noop(self) -> None:
        state = MARSState()
        _nav_mcp(state, 1)             # Should not raise
