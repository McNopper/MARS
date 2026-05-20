"""Central constant definitions for MARS.

All magic numbers and magic strings live here.  Import directly from this
module so that any change to a value is made in exactly one place.
"""
from __future__ import annotations

# ── Agent / role types ───────────────────────────────────────────────────────

AGENT_TYPE_LLM      = "LLMAgent"
AGENT_TYPE_SERVICE  = "ServiceAgent"
AGENT_TYPE_HUMAN    = "HumanUser"
AGENT_TYPE_ECHO     = "EchoBot"
AGENT_TYPE_BRIDGE   = "CLIBridgeAgent"

# Default skill tags advertised by LLM agents
DEFAULT_LLM_SKILLS: list[str] = ["llm", "chat", "reasoning"]

# ── Agent registry / agents.ini ──────────────────────────────────────────────

COST_FREE   = "free"
COST_DEMAND = "demand"

PROTOCOL_MCP = "mcp"
PROTOCOL_TCP = "tcp"

CATEGORY_SERVICE  = "service"
CATEGORY_EXTERNAL = "external"

# ── Network defaults ─────────────────────────────────────────────────────────

DEFAULT_PORT            = 7432
DEFAULT_HTTP_PORT       = 7433
DEFAULT_WS_PORT         = 7434
DEFAULT_FEDERATION_PORT = 7435

# ── MCP protocol ─────────────────────────────────────────────────────────────

MCP_PROTOCOL_VERSION        = "2024-11-05"
MCP_CLIENT_NAME             = "mars-server"
MCP_CLIENT_VERSION          = "1.0"
MCP_NOTIFICATION_INITIALIZED = "notifications/initialized"
MCP_CONTENT_TYPE_TEXT       = "text"

# 16 MB — needed for servers that return large tool lists (e.g. GitHub MCP)
MCP_BUFFER_SIZE = 16 * 1024 * 1024

# ── Timeouts and limits ──────────────────────────────────────────────────────

MCP_TIMEOUT          = 30.0  # seconds to wait for an MCP tools/call response
TOOL_CALL_TIMEOUT    = 30.0  # seconds the LLM wire agent waits for a service reply
MAX_TOOL_ITERATIONS  = 8     # max LLM → tool → LLM loops per request
PROCESS_TERM_TIMEOUT = 3.0   # seconds to wait for a subprocess to exit cleanly
GRACE_PERIOD_SECONDS = 1.5   # pause between SIGTERM and force-kill

# ── Structured tool-call envelope ────────────────────────────────────────────
# Wire agents embed tool calls in plain text using this JSON envelope so the
# server can route them to the correct MCP tool with the correct arguments.

TOOL_KEY      = "__tool__"
TOOL_ARGS_KEY = "__args__"

# ── UI / history limits ──────────────────────────────────────────────────────

CHAT_HISTORY_MAXLEN = 200
FEED_MAXLEN         = 30


