"""Sidebar / connections / MCP / services panel navigation helpers.

These are CLI-only TUI helpers: they operate on :class:`~mars.common.state.MARSState`
cursor/scroll fields and contain no rendering logic.
"""
from __future__ import annotations

from mars.common.agent_record import AgentRecord
from mars.common.state import MARSState

# ---------------------------------------------------------------------------
# Sidebar navigation helpers
# ---------------------------------------------------------------------------

_SIDEBAR_PINNED: tuple = ()  # no agents pinned at top (echo bots hidden)

_CONVERSATIONAL_TYPES = frozenset({
    "LLMAgent", "HumanUser", "CLIBridgeAgent", "BridgeAgent",
})


def _is_conversational(rec: AgentRecord) -> bool:
    return getattr(rec, "agent_type", "LLMAgent") in _CONVERSATIONAL_TYPES


def _sidebar_agent_ids(state: MARSState) -> list[str]:
    """Return the ordered list of conversational agent IDs (navigable in sidebar)."""
    pinned = [aid for aid in _SIDEBAR_PINNED if aid in state.agents]
    others = [
        aid for aid in state.agents
        if aid not in _SIDEBAR_PINNED and _is_conversational(state.agents[aid])
    ]
    return pinned + others


def _nav_sidebar(state: MARSState, delta: int) -> None:
    """Move sidebar cursor by *delta* rows in server→category→item hierarchy view."""
    # Group by server, then by category
    servers: dict[str, dict[str, list[tuple[str, AgentRecord]]]] = {}
    nav_ids = _sidebar_agent_ids(state)
    for aid in nav_ids:
        if aid in state.agents:
            rec = state.agents[aid]
            server = rec.server_addr or "local"
            if server not in servers:
                servers[server] = {"User": [], "_providers": {}}

            if rec.agent_type in ("HumanUser", "HUMAN"):
                servers[server]["User"].append((aid, rec))
            else:
                provider = rec.vendor or "unknown"
                if provider not in servers[server]["_providers"]:
                    servers[server]["_providers"][provider] = []
                servers[server]["_providers"][provider].append((aid, rec))

    if not servers:
        return

    # Build row index: (row_number, level, server, category, agent_id)
    # level: 0 = server, 1 = category, 2 = item
    rows: list[tuple[int, int, str, str | None, str | None]] = []
    current_row = 0

    for server, categories in sorted(servers.items()):
        rows.append((current_row, 0, server, None, None))
        current_row += 1

        is_server_expanded = state.sidebar_servers_expand.get(server, False)
        if is_server_expanded:
            # User category
            if categories["User"]:
                rows.append((current_row, 1, server, "User", None))
                current_row += 1

                cat_key = f"{server}:User"
                is_cat_expanded = state.sidebar_categories_expand.get(cat_key, False)
                if is_cat_expanded:
                    for aid, rec in categories["User"]:
                        rows.append((current_row, 2, server, "User", aid))
                        current_row += 1

            # Provider categories
            for provider in sorted(categories["_providers"].keys()):
                rows.append((current_row, 1, server, provider, None))
                current_row += 1

                cat_key = f"{server}:{provider}"
                is_cat_expanded = state.sidebar_categories_expand.get(cat_key, False)
                if is_cat_expanded:
                    for aid, rec in categories["_providers"][provider]:
                        rows.append((current_row, 2, server, provider, aid))
                        current_row += 1

    if not rows:
        return

    # Move cursor
    total_rows = len(rows)
    new_cursor = max(0, min(state.sidebar_cursor + delta, total_rows - 1))
    state.sidebar_cursor = new_cursor

    # Scroll-follow
    win = max(1, state.sidebar_visible_height)
    if new_cursor < state.sidebar_scroll:
        state.sidebar_scroll = new_cursor
    elif new_cursor >= state.sidebar_scroll + win:
        state.sidebar_scroll = new_cursor - win + 1

    # Selection is now handled by Communications panel, not sidebar
    # The sidebar is purely for viewing the hierarchy


def _nav_sidebar_toggle_expand(state: MARSState, expand: bool) -> None:
    """Toggle expansion of the server or category at current cursor position."""
    # Group by server, then by category
    servers: dict[str, dict[str, list[tuple[str, AgentRecord]]]] = {}
    nav_ids = _sidebar_agent_ids(state)
    for aid in nav_ids:
        if aid in state.agents:
            rec = state.agents[aid]
            server = rec.server_addr or "local"
            if server not in servers:
                servers[server] = {"User": [], "_providers": {}}

            if rec.agent_type in ("HumanUser", "HUMAN"):
                servers[server]["User"].append((aid, rec))
            else:
                provider = rec.vendor or "unknown"
                if provider not in servers[server]["_providers"]:
                    servers[server]["_providers"][provider] = []
                servers[server]["_providers"][provider].append((aid, rec))

    if not servers:
        return

    # Build row index to find what's at cursor
    rows: list[tuple[int, int, str, str | None]] = []  # (row_number, level, server, category)
    # level: 0 = server, 1 = category
    current_row = 0

    for server, categories in sorted(servers.items()):
        rows.append((current_row, 0, server, None))
        current_row += 1

        is_server_expanded = state.sidebar_servers_expand.get(server, False)
        if is_server_expanded:
            # User category
            if categories["User"]:
                rows.append((current_row, 1, server, "User"))
                current_row += 1

                cat_key = f"{server}:User"
                is_cat_expanded = state.sidebar_categories_expand.get(cat_key, False)
                if is_cat_expanded:
                    current_row += len(categories["User"])

            # Provider categories
            for provider in sorted(categories["_providers"].keys()):
                rows.append((current_row, 1, server, provider))
                current_row += 1

                cat_key = f"{server}:{provider}"
                is_cat_expanded = state.sidebar_categories_expand.get(cat_key, False)
                if is_cat_expanded:
                    current_row += len(categories["_providers"][provider])

    # Find what's at cursor
    if state.sidebar_cursor >= len(rows):
        return

    row_num, level, server_name, category_name = rows[state.sidebar_cursor]

    if level == 0:  # Server row
        state.sidebar_servers_expand[server_name] = expand
    elif level == 1 and category_name:  # Category row
        cat_key = f"{server_name}:{category_name}"
        state.sidebar_categories_expand[cat_key] = expand


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


# ---------------------------------------------------------------------------
# MCP panel navigation helpers
# ---------------------------------------------------------------------------

def _mcp_agent_ids(state: MARSState) -> list[str]:
    """Sorted list of MCP service agent IDs (non-conversational, non-echo)."""
    return sorted(
        aid for aid, rec in state.agents.items()
        if not _is_conversational(rec) and rec.agent_type != "EchoBot"
    )


def _nav_mcp(state: MARSState, delta: int) -> None:
    """Move the MCP cursor by *delta* rows and scroll-follow to keep it visible."""
    ids = _mcp_agent_ids(state)
    if not ids:
        return
    cursor = max(0, min(state.mcp_cursor + delta, len(ids) - 1))
    state.mcp_cursor = cursor
    win = max(1, state.mcp_visible_height)
    if cursor < state.mcp_scroll:
        state.mcp_scroll = cursor
    elif cursor >= state.mcp_scroll + win:
        state.mcp_scroll = cursor - win + 1


def _nav_services(state: MARSState, delta: int) -> None:
    """Move the Services cursor by *delta* rows and scroll-follow to keep it visible.

    Uses ``state.discovered_services`` (populated from the wire state frame) so
    navigation works with the same data the panel renders — no server imports.
    """
    services = state.discovered_services
    if not services:
        return

    # Build flat row list matching what render_services draws
    by_type: dict[str, list[dict]] = {"llm": [], "mcp": [], "a2a": [], "builtin": []}
    for svc in services:
        by_type.setdefault(svc.get("type", "builtin"), []).append(svc)

    total = sum(
        1 + len(by_type[t])          # 1 header + N items
        for t in ("llm", "mcp", "a2a", "builtin")
        if by_type[t]
    )
    if total == 0:
        return

    cursor = max(0, min(state.services_cursor + delta, total - 1))
    state.services_cursor = cursor

    win = max(1, state.services_visible_height)
    if cursor < state.services_scroll:
        state.services_scroll = cursor
    elif cursor >= state.services_scroll + win:
        state.services_scroll = cursor - win + 1
