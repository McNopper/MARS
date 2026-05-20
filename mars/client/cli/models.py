from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mars.constants import (
    AGENT_TYPE_BRIDGE,
    AGENT_TYPE_ECHO,
    AGENT_TYPE_HUMAN,
    AGENT_TYPE_LLM,
    AGENT_TYPE_SERVICE,
    CHAT_HISTORY_MAXLEN,
    FEED_MAXLEN,
)

HUMAN_AVATARS: list[str] = [
    # People
    "🧑", "👤", "👩", "👨", "🧒", "👧", "👦", "👴", "👵", "🧓",
    # Roles & professions
    "🧑‍💻", "👩‍💻", "👨‍💻", "🧑‍🔬", "👩‍🔬", "👨‍🔬",
    "🧑‍🎨", "👩‍🎨", "👨‍🎨", "🧑‍🏫", "👩‍🏫", "👨‍🏫",
    "🧑‍⚕️", "👩‍⚕️", "👨‍⚕️", "🧑‍🚀", "👩‍🚀", "👨‍🚀",
    "🧑‍✈️", "👩‍✈️", "👨‍✈️", "🕵️", "👮", "💂",
    # Fantastical / fun
    "🧙", "🧝", "🧛", "🧟", "🧞", "🧜", "🧚",
    "🦸", "🦹", "🤴", "👸", "🤖", "👽", "👾", "🎭",
]

AGENT_EMOJIS: dict[str, str] = {
    AGENT_TYPE_LLM:     "🤖",
    AGENT_TYPE_ECHO:    "🔊",
    "SensorAgent":      "🤖",
    AGENT_TYPE_BRIDGE:  "🖥️",
    AGENT_TYPE_HUMAN:   "🙂",
    AGENT_TYPE_SERVICE: "🔧",
    "BridgeAgent":      "🌉",
    "GroupRoom":        "💬",
    "Agent":            "🤖",
}

# Per-vendor emoji for LLM agents — overrides the generic 🤖
VENDOR_EMOJIS: dict[str, str] = {
    "ollama":    "🦙",   # Ollama — named after llamas
    "copilot":   "🐙",   # GitHub Copilot — Octocat
    "anthropic": "🧠",   # Anthropic / Claude
    "mock":      "🎭",   # offline mock agent
}


EVENT_ICONS: dict[str, str] = {
    "spawn":    "🟢",
    "despawn":  "🔴",
    "fed":      "🔗",
    "message":  "💬",
    "reply":    "💬",
    "state":    "🔄",
}


@dataclass
class ChatMessage:
    ts: datetime
    sender: str
    content: str
    direction: str = "out"   # "out" = user→agent, "in" = agent→user
    attachment: bytes | None = None      # raw bytes of an inline image preview
    attachment_mime: str = ""            # e.g. "image/png"
    attachment_name: str = ""            # e.g. "formula.png"


@dataclass
class AgentRecord:
    agent_id: str
    agent_type: str = "Agent"
    domain: str = "default"
    platform: str = "local"
    is_current: bool = False
    status: str = "active"
    fsm_state: str = "—"
    fsm_strategy: str = "—"
    fsm_loop: str | None = None     # loop progress label when active
    has_reply: bool = False         # reserved for wire protocol compatibility
    pending_reply: str = ""         # reserved for wire protocol compatibility
    verbose: bool = False
    avatar: str = ""                # custom avatar emoji (humans only)
    model: str = ""                 # model identifier (e.g. "gpt-4o", "llama-3.3-70b")
    vendor: str = ""                # provider/vendor name (e.g. "openai", "ollama")
    competence_level: str = "COMPETENT"  # CompetenceLevel label from CompetenceManager
    competence_score: float = 50.0       # 0-100 numeric competence
    server_addr: str = ""                # host:port of the MARS server this agent belongs to
    chat: deque = field(default_factory=lambda: deque(maxlen=CHAT_HISTORY_MAXLEN))
    skills: list = field(default_factory=list)  # capability tags for auto-assignment
    tool_schemas: list = field(default_factory=list)  # [{name, description, input_schema}] for MCP tools


# Short role prefix used in the sidebar address label (role.name@host:port)
_AGENT_ROLE: dict[str, str] = {
    AGENT_TYPE_LLM:     "llm",
    AGENT_TYPE_SERVICE: "service",
    AGENT_TYPE_HUMAN:   "human",
    "BridgeAgent":      "bridge",
    AGENT_TYPE_ECHO:    "echo",
    AGENT_TYPE_BRIDGE:  "cli",
    "SensorAgent":      "sensor",
    "ProactiveAgent":   "pro",
    "ReactiveAgent":    "re",
    "Agent":            "agent",
}

@dataclass
class FeedItem:
    ts: datetime
    event_type: str          # message | spawn | despawn | state | fed
    from_id: str
    to_id: str
    snippet: str
    performative: str = "INFORM"


DEFAULT_PORT = 7432
DEFAULT_FEDERATION_PORT = 7435


@dataclass
class MARSState:
    platform_name: str = "mars"
    agents: dict[str, AgentRecord] = field(default_factory=dict)
    feed: deque[FeedItem] = field(default_factory=lambda: deque(maxlen=FEED_MAXLEN))
    current_agent: str | None = None
    # Group rooms: room_name → set of member agent_ids.
    # When current_agent == "#<room_name>" the feed shows the room chat.
    rooms: dict[str, set[str]] = field(default_factory=dict)
    rooms_chat: dict[str, Any] = field(default_factory=dict)  # room_name → deque[ChatMessage]
    federation_peers: list[str] = field(default_factory=list)
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
    # which panel has keyboard focus: "sidebar" | "chat" | "connections"
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
            try:
                cb(ev)
            except Exception:
                pass

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


# ---------------------------------------------------------------------------
# Sidebar navigation helpers
# ---------------------------------------------------------------------------

_SIDEBAR_PINNED: tuple = ()  # no agents pinned at top (echo bots hidden)

_CONVERSATIONAL_TYPES = frozenset({
    "LLMAgent", "HumanUser", "CLIBridgeAgent", "BridgeAgent",
})


def _is_conversational(rec: "AgentRecord") -> bool:
    return getattr(rec, "agent_type", "LLMAgent") in _CONVERSATIONAL_TYPES


def _sidebar_agent_ids(state: "MARSState") -> list[str]:
    """Return the ordered list of conversational agent IDs (navigable in sidebar)."""
    pinned = [aid for aid in _SIDEBAR_PINNED if aid in state.agents]
    others = [
        aid for aid in state.agents
        if aid not in _SIDEBAR_PINNED and _is_conversational(state.agents[aid])
    ]
    return pinned + others


def _nav_sidebar(state: "MARSState", delta: int) -> None:
    """Move sidebar cursor by *delta* rows and immediately switch current_agent."""
    agent_ids = _sidebar_agent_ids(state)
    if not agent_ids:
        return
    cursor = max(0, min(state.sidebar_cursor + delta, len(agent_ids) - 1))
    state.sidebar_cursor = cursor
    # Scroll-follow: only move the list when the cursor leaves the visible window
    win = max(1, state.sidebar_visible_height)
    if cursor < state.sidebar_scroll:
        state.sidebar_scroll = cursor
    elif cursor >= state.sidebar_scroll + win:
        state.sidebar_scroll = cursor - win + 1
    new_agent = agent_ids[cursor]
    for rec in state.agents.values():
        rec.is_current = False
    # Conversational agents (LLM, human) always communicate via their auto-room.
    rec = state.agents.get(new_agent)
    if rec is not None and _is_conversational(rec) and new_agent in state.rooms:
        state.current_agent = f"#{new_agent}"
    else:
        state.current_agent = new_agent
    state.chat_scroll = 0
    if new_agent in state.agents:
        state.agents[new_agent].is_current = True


def _sync_sidebar_cursor(state: "MARSState") -> None:
    """Sync sidebar_cursor to match current_agent (call after /switch or agent events)."""
    agent_ids = _sidebar_agent_ids(state)
    # Strip '#' prefix — sidebar always indexes by plain agent IDs, not room names.
    target = state.current_agent.lstrip("#") if state.current_agent else ""
    if target in agent_ids:
        idx = agent_ids.index(target)
        state.sidebar_cursor = idx
        # Scroll-follow: keep sidebar_scroll at 0 unless the cursor is outside the
        # visible window.  Never jump scroll to the cursor unconditionally — that
        # hides agents above the current one when first spawned.
        win = max(1, state.sidebar_visible_height)
        if idx < state.sidebar_scroll:
            state.sidebar_scroll = idx
        elif idx >= state.sidebar_scroll + win:
            state.sidebar_scroll = idx - win + 1
