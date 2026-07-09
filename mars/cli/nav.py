"""Services / connections panel navigation helpers.

These are CLI-only TUI helpers: they operate on :class:`~mars.common.state.MARSState`
cursor/scroll fields and contain no rendering logic.
"""
from __future__ import annotations

from mars.common.agent_record import AgentRecord
from mars.common.state import MARSState

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CONVERSATIONAL_TYPES = frozenset({
    "LLMAgent", "HumanUser", "CLIBridgeAgent", "BridgeAgent",
})


def _is_conversational(rec: AgentRecord) -> bool:
    return getattr(rec, "agent_type", "LLMAgent") in _CONVERSATIONAL_TYPES


def _sidebar_agent_ids(state: MARSState) -> list[str]:
    """Return the ordered list of conversational agent IDs."""
    return [
        aid for aid in state.agents
        if _is_conversational(state.agents[aid])
    ]


def _nav_connections(state: MARSState, delta: int) -> None:
    """Move connections panel cursor by delta in hierarchical view and set current_agent."""
    # Build conversation hierarchy: user agent → conversational agents they can chat with
    conversations: dict[str, list[str]] = {}

    # Get all conversational agents (excluding user)
    conv_agents = []
    for aid, rec in state.agents.items():
        if aid != state.my_agent_id and _is_conversational(rec):
            conv_agents.append(aid)

    # User agent shows all conversational agents as potential chat partners
    if state.my_agent_id in state.agents:
        conversations[state.my_agent_id] = sorted(conv_agents)

    if not conversations:
        return

    # Build flat list of (agent_or_partner_id, is_agent) for navigation
    items: list[tuple[str, bool]] = []
    for agent, partners in sorted(conversations.items()):
        items.append((agent, True))  # agent (parent)
        for partner in partners:
            items.append((partner, False))  # partner (child)

    if not items:
        return

    cursor = max(0, min(state.connections_cursor + delta, len(items) - 1))
    state.connections_cursor = cursor

    # Scroll-follow
    win = max(1, state.connections_visible_height)
    if cursor < state.connections_scroll:
        state.connections_scroll = cursor
    elif cursor >= state.connections_scroll + win:
        state.connections_scroll = cursor - win + 1

    # Set current_agent to the selected item
    selected_id, is_agent = items[cursor]
    if not is_agent:
        # Only set current_agent when selecting a partner (child), not agent (parent)
        state.current_agent = selected_id
        state.chat_scroll = 0


def _sync_sidebar_cursor(state: MARSState) -> None:
    """Sync sidebar_cursor to match current_agent (call after /switch or agent events)."""
    agent_ids = _sidebar_agent_ids(state)
    target = state.current_agent or ""
    if target in agent_ids:
        idx = agent_ids.index(target)
        state.sidebar_cursor = idx
        # Scroll-follow: keep sidebar_scroll at 0 unless the cursor is outside the
        # visible window. Never jump scroll to the cursor unconditionally — that
        # hides agents above the current one when first spawned.
        win = max(1, state.sidebar_visible_height)
        if idx < state.sidebar_scroll:
            state.sidebar_scroll = idx
        elif idx >= state.sidebar_scroll + win:
            state.sidebar_scroll = idx - win + 1


def _build_services_rows(state: MARSState) -> list[tuple]:
    """Build the flat navigable row list for the services panel.

    Returns a list of tuples:
      ("section",      svc_type)                 — section header row
      ("provider",     provider_name)             — LLM provider (expandable)
      ("model",        provider_name, model_id)   — model sub-item (when expanded)
      ("service_item", svc_name)                  — MCP service item
    """
    services = state.discovered_services
    by_type: dict[str, list[dict]] = {"llm": [], "service": []}
    for svc in services:
        raw = svc.get("type", "service")
        bucket = raw if raw in by_type else "service"
        by_type[bucket].append(svc)

    rows: list[tuple] = []
    for svc_type in ("llm", "service"):
        if not by_type[svc_type]:
            continue
        rows.append(("section", svc_type))
        for svc in by_type[svc_type]:
            name = svc["name"]
            if svc_type == "llm":
                rows.append(("provider", name))
                if state.services_expanded.get(name):
                    for mid in state.provider_models.get(name, []):
                        rows.append(("model", name, mid))
            else:
                rows.append(("service_item", name))
    return rows


def _nav_services(state: MARSState, delta: int) -> None:
    """Move the Services cursor by *delta* rows and scroll-follow to keep it visible."""
    rows = _build_services_rows(state)
    total = len(rows)
    if total == 0:
        return

    cursor = max(0, min(state.services_cursor + delta, total - 1))
    state.services_cursor = cursor

    win = max(1, state.services_visible_height)
    if cursor < state.services_scroll:
        state.services_scroll = cursor
    elif cursor >= state.services_scroll + win:
        state.services_scroll = cursor - win + 1
