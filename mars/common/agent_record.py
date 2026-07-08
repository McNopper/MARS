"""Core data records, avatar/emoji tables, and role/port constants for MARS."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from mars.common.constants import (
    AGENT_TYPE_BRIDGE,
    AGENT_TYPE_ECHO,
    AGENT_TYPE_HUMAN,
    AGENT_TYPE_LLM,
    AGENT_TYPE_PROVIDER,
    CHAT_HISTORY_MAXLEN,
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
    AGENT_TYPE_LLM:      "🤖",
    AGENT_TYPE_ECHO:     "🔊",
    "SensorAgent":       "🤖",
    AGENT_TYPE_BRIDGE:   "🖥️",
    AGENT_TYPE_HUMAN:    "🙂",
    AGENT_TYPE_PROVIDER: "🔧",
    "BridgeAgent":       "🌉",
    "Agent":             "🤖",
}

# Per-vendor emoji for LLM agents — overrides the generic 🤖
VENDOR_EMOJIS: dict[str, str] = {
    "ollama":    "🦙",   # Ollama — named after llamas
    "copilot":   "🐙",   # GitHub Copilot — Octocat
    "anthropic": "✳️",   # Anthropic / Claude — radial "sunburst" mark
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
    AGENT_TYPE_LLM:      "llm",
    AGENT_TYPE_PROVIDER: "provider",
    AGENT_TYPE_HUMAN:    "human",
    "BridgeAgent":       "bridge",
    AGENT_TYPE_ECHO:     "echo",
    AGENT_TYPE_BRIDGE:   "cli",
    "SensorAgent":       "sensor",
    "ProactiveAgent":    "pro",
    "ReactiveAgent":     "re",
    "Agent":             "agent",
}

@dataclass
class FeedItem:
    ts: datetime
    event_type: str          # message | spawn | despawn | state | fed
    from_id: str
    to_id: str
    snippet: str
    performative: str = "INFORM"


@dataclass
class A2APeer:
    """A remote MARS (or A2A-compliant) node connected as a peer."""
    agent_id: str       # local ID, e.g. "a2a.mars-node-2@1"
    url: str            # base URL of the remote node's HTTP REST API
    name: str           # from Agent Card
    description: str = ""
    skills: list[str] = field(default_factory=list)


DEFAULT_PORT = 7432
DEFAULT_FEDERATION_PORT = 7435
