"""The MARSState aggregate: the single source of truth shared across the CLI and server."""
from __future__ import annotations

import contextlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from mars.common.agent_record import (
    AGENT_EMOJIS,
    VENDOR_EMOJIS,
    AgentRecord,
    FeedItem,
)
from mars.common.constants import AGENT_TYPE_LLM, FEED_MAXLEN


@dataclass
class MARSState:
    platform_name: str = "mars"
    agents: dict[str, AgentRecord] = field(default_factory=dict)
    feed: deque[FeedItem] = field(default_factory=lambda: deque(maxlen=FEED_MAXLEN))
    current_agent: str | None = None
    # echo_mode controls how incoming agent replies are rendered:
    #   "md"    — full markdown rendering (default, matches echo-md)
    #   "text"  — plain text only (matches echo-text)
    #   "void"  — discard, do not render incoming replies at all (matches echo-void)
    echo_mode: str = "md"
    # currently displayed reply (set by /read or /switch-to-agent-with-reply)
    reply_agent: str = ""
    reply_content: str = ""
    # transient status line shown above the prompt (cleared on next input)
    status_line: str = ""
    status_style: str = ""
    # scopes board
    scopes: list = field(default_factory=list)
    # agent role/goal/behaviour metadata (set on spawn, used in sidebar)
    agent_roles: dict[str, str] = field(default_factory=dict)      # agent_id → role
    agent_behaviours: dict[str, str] = field(default_factory=dict) # agent_id → "reactive" | "proactive"
    chat_scroll: int = 0
    sidebar_scroll: int = 0
    # visible window height for the sidebar (updated each render; used for scroll-follow)
    sidebar_visible_height: int = 20
    # cursor index into the ordered sidebar agent list (for keyboard/wheel nav)
    sidebar_cursor: int = 0
    # server expansion state — unused, kept for wire compatibility
    sidebar_servers_expand: dict[str, bool] = field(default_factory=dict)
    sidebar_categories_expand: dict[str, bool] = field(default_factory=dict)
    connections_cursor: int = 0
    connections_scroll: int = 0
    connections_visible_height: int = 10
    # Services panel navigation
    services_cursor: int = 0
    services_scroll: int = 0
    services_visible_height: int = 10
    # Service registry received from server via the state frame.
    # Format: [{"name": str, "type": str, "free": bool, "default": bool}, ...]
    # Populated by apply_event("state") — same frame any agent receives on connect.
    discovered_services: list = field(default_factory=list)
    # Available models per LLM provider — populated by "models" event after connect.
    # Format: {"ollama": ["qwen3:4b", "llama3.2", ...], "copilot": ["gpt-4o", ...]}
    provider_models: dict = field(default_factory=dict)
    # Expand/collapse state for LLM providers in the services panel.
    services_expanded: dict = field(default_factory=dict)
    # which panel has keyboard focus: "chat" | "services" | "connections"
    panel_focus: str = "chat"
    # this CLI's own agent ID — 🏠 in sidebar; set at startup
    my_agent_id: str = "cli-user@1"
    # event broadcasting: server registers a callback here to push events to TCP clients
    _event_listeners: list = field(default_factory=list, repr=False)
    # pending code execution permission requests: request_id → {code, requesting_agent, executor_agent, language}
    pending_permissions: dict = field(default_factory=dict)

    def _fire(self, ev: dict) -> None:
        """Notify all registered event listeners (used by the server to broadcast over TCP)."""
        for cb in self._event_listeners:
            with contextlib.suppress(Exception):
                cb(ev)

    def emoji(self, agent_id: str) -> str:
        rec = self.agents.get(agent_id)
        if rec is None:
            return "👤"
        # Humans may choose a custom avatar; bots always use their type icon
        if rec.avatar and rec.agent_type in ("HumanUser", "CLIBridgeAgent"):
            return rec.avatar
        # LLM agents: use vendor-specific emoji when available
        if rec.agent_type == AGENT_TYPE_LLM and rec.vendor:
            vendor_em = VENDOR_EMOJIS.get(rec.vendor.lower())
            if vendor_em:
                return vendor_em
        return AGENT_EMOJIS.get(rec.agent_type, "👤")

    def add_event(self, event_type: str, agent_id: str, detail: str = "") -> None:
        ts = datetime.now()
        snippet = detail or agent_id
        self.feed.append(FeedItem(
            ts=ts, event_type=event_type,
            from_id="system", to_id=agent_id,
            snippet=snippet,
        ))
        self._fire({"t": "feed", "event_type": event_type,
                    "from_id": "system", "to_id": agent_id,
                    "snippet": snippet, "ts": ts.isoformat(), "performative": "INFORM"})
