"""MARS Service Registry – unified factory for all services.

Usage
-----
    from mars.server.services import get_service, list_services

    # LLM agents
    ollama = get_service("ollama", model="llama3.2")
    anthropic = get_service("anthropic")

    # Services (all accessed via MCP)
    federation = get_service("federation", url="http://localhost:8000")

    print(list_services())
    # ['anthropic', 'ollama', 'copilot', 'filesystem', 'status', ...]

Adding a new service
--------------------
1. Create service class in appropriate subdirectory:
   - LLM agents: mars/server/services/llm/
   - Services (MCP): mars/server/services/builtin/, mcp/, a2a/
2. Add entry to REGISTRY below.
3. Add to DEFAULT_SERVICES if it should start automatically.

Service types
-------------
* llm     - Language model providers (Ollama, Anthropic, Copilot) — conversational agents
* service - MCP Services: builtin utilities, MCP servers, A2A peers
            All exposed and discovered through MCP protocol.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import shlex
from typing import Any

from mars.server.services.base import Service


# ---------------------------------------------------------------------------
# Availability checks — credential probes, no network calls
# ---------------------------------------------------------------------------

def _available_ollama() -> bool:
    """True if the Ollama HTTP server is reachable (TCP connect, no network I/O beyond LAN)."""
    import socket
    import urllib.parse
    host_env = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    parsed = urllib.parse.urlparse(host_env if "://" in host_env else f"http://{host_env}")
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False



def _available_copilot() -> bool:
    """True if a Copilot OAuth token is resolvable — mirrors CopilotService._get_token()."""
    import contextlib
    import shutil
    import subprocess
    for var in ("COPILOT_API_KEY", "GH_COPILOT_TOKEN", "GITHUB_COPILOT_TOKEN"):
        if os.environ.get(var):
            return True
    if not shutil.which("gh"):
        return False
    with contextlib.suppress(Exception):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=2, env=env,
        )
        return bool(result.stdout.strip())
    return False


def _available_anthropic() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY"))


def _not_available() -> bool:
    """Services that require explicit user configuration before they can be used."""
    return False


# Map service name → availability probe (None = always available)
_AVAILABILITY: dict[str, Any] = {
    "copilot":     _available_copilot,
    "anthropic":   _available_anthropic,
    "ollama":      _available_ollama,
    # MCP services need a user-supplied command — not usable out of the box
    "filesystem":  _not_available,
    # A2A needs a peer address to connect to
    "federation":  _not_available,
}


def _is_available(name: str) -> bool:
    """Return True if *name* has the credentials/prerequisites it needs."""
    probe = _AVAILABILITY.get(name)
    if probe is None:
        return True  # service — always considered available
    return bool(probe())


# ---------------------------------------------------------------------------
# Legacy AgentSpec for service_manager compatibility
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class AgentSpec:
    """Agent specification for service spawning (legacy compatibility)."""
    name: str
    command: str
    cost: str = "demand"  # "free" or "demand"
    description: str = ""
    skills: list[str] = dataclasses.field(default_factory=list)
    category: str = "provider"
    protocol: str = "tcp"  # "tcp" = wire agent subprocess; "mcp" = stdio MCP adapter


def all_specs() -> list[AgentSpec]:
    """Return all agent specs from agents.ini (legacy compatibility)."""
    # For now, return empty list - this functionality may be replaced by service registry
    return []


def get_agent_spec(name: str) -> AgentSpec | None:
    """Get an AgentSpec for legacy code compatibility.

    This function provides backward compatibility for code that expects
    AgentSpec objects with protocol, command, and other legacy fields.
    It converts the new Service-based registry into the old AgentSpec format.

    Returns None for LLM services - these should use the wire agent spawning
    logic instead of the legacy provider spawning.
    """
    key = name.lower().strip()
    key = _ALIASES.get(key, key)

    entry = REGISTRY.get(key)
    if entry is None:
        return None

    module_path, class_name, service_type, is_default, _ = entry

    # LLM services should use wire agent spawning, not legacy provider spawning
    if service_type == "llm":
        return None

    return AgentSpec(
        name=key,
        command=f"python -m mars.server.services.{key}",
        cost="free" if key in FREE_SERVICES else "demand",
        description=f"{key} service",
        skills=[],
        category="provider",
        protocol="mcp",
    )


def resolve_command(cmd_str: str) -> list[str]:
    """Resolve command string to list of arguments (legacy compatibility)."""
    return shlex.split(cmd_str)

# Registry: service name → (module path, class name, service_type, default, test_only)
# Lazy imports – the module is only loaded when get_service() is called.
#
# service_type is one of:
#   "llm"     — conversational LLM agent (spawned as a wire process)
#   "service" — MCP Service: builtin utility, external MCP server, or A2A peer
#               all discovered and invoked through MCP protocol
REGISTRY: dict[str, tuple[str, str, str, bool, bool]] = {
    # === LLM Agents ===
    # GitHub Copilot Chat (uses GITHUB_TOKEN / gh auth login – no extra SDK)
    "copilot":   ("mars.server.services.llm.copilot",   "CopilotService",      "llm", False, False),
    # Anthropic Claude (pip install anthropic + ANTHROPIC_API_KEY)
    "anthropic": ("mars.server.services.llm.anthropic", "AnthropicService",    "llm", False, False),
    # Local Ollama server (https://ollama.com – no API key required)
    "ollama":    ("mars.server.services.llm.ollama",    "OllamaService",       "llm", False, False),
    # Mock provider – offline testing only, not shown in the services panel
    "mock":      ("mars.server.services.llm.mock",      "MockService",         "llm", False, True),
    # Mock provider that emits tool calls – for tool round-trip tests only
    "mock-tool": ("mars.server.services.llm.mock",      "ToolCallMockService",  "llm", False, True),

    # === Services (all accessed via MCP) ===
    # -- Builtin (in-process, start automatically) --
    # Discovery service (primary bootstrap — LLMs receive this on spawn)
    "discovery":    ("mars.server.services.builtin.discovery",        "DiscoveryService",             "service", True,  False),
    # Status service (runtime introspection)
    "status":       ("mars.server.services.builtin.status_service",   "StatusService",                "service", True,  False),
    # Launcher service (spawn new LLM agents at runtime)
    "launcher":     ("mars.server.services.builtin.launcher_service", "LauncherService",              "service", True,  False),
    # Profiler (performance monitoring, off by default)
    "profiler":     ("mars.server.services.builtin.profiler",         "ProfilerService",              "service", False, False),
    # CLI connection management
    "cli":          ("mars.server.services.builtin.cli_service",      "CLIService",                   "service", True,  False),
    # -- External MCP servers (require user-supplied command) --
    # MCP filesystem server (stdio)
    "filesystem":   ("mars.server.services.mcp.service",              "MCPService",                   "service", False, False),
    # -- A2A peers (require peer address) --
    # A2A peer connection to a remote MARS instance
    "federation":   ("mars.server.services.a2a.service",              "A2AService",                   "service", False, False),
}

# Aliases
_ALIASES: dict[str, str] = {
    "claude": "anthropic",
}

# Services that start automatically with MARS
DEFAULT_SERVICES: list[str] = [
    "discovery",   # Dynamic service discovery for LLMs (primary bootstrap service)
    "status",      # Core status service
    "launcher",    # Agent launcher
    "cli",         # CLI connection handler
]

# Free-tier services (no API cost)
FREE_SERVICES: set[str] = {
    "copilot",      # Free tier available
    "ollama",       # Local, no API cost
    "filesystem",   # Local MCP server
}


def get_service(name: str, **kwargs: Any) -> Service:
    """Instantiate a service by name.

    Parameters
    ----------
    name:
        Service name (case-insensitive), e.g. ``"copilot"``, ``"ollama"``.
        Aliases are resolved automatically.
    **kwargs:
        Forwarded to the service's ``__init__``.  Common ones:
        ``model``, ``api_key``, ``host``, ``command`` (for MCP).

    Raises
    ------
    ValueError
        If the service name is unknown.
    ImportError
        If a required SDK package is not installed.
    """
    key = name.lower().strip()
    key = _ALIASES.get(key, key)

    entry = REGISTRY.get(key)
    if entry is None:
        services = ", ".join(sorted(REGISTRY))
        aliases = ", ".join(f"{alias}→{target}" for alias, target in sorted(_ALIASES.items()))
        raise ValueError(
            f"Unknown service {name!r}. Available services: {services}. "
            f"Aliases: {aliases}"
        )

    module_path, class_name, _, _ , _ = entry
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(**kwargs)


def list_services(service_type: str | None = None, include_test: bool = False) -> list[str]:
    """Return sorted list of registered services, optionally filtered by type.

    Test-only services (``mock``, ``mock-tool``) are excluded by default.
    Pass ``include_test=True`` to include them (used by the test suite).
    """
    return sorted([
        name for name, (_, _, st, _, test_only) in REGISTRY.items()
        if (not test_only or include_test)
        and (service_type is None or st == service_type)
    ])


def list_default_services() -> list[str]:
    """Return list of services that start by default."""
    return DEFAULT_SERVICES.copy()


def service_info() -> list[dict[str, Any]]:
    """Return metadata about all non-test services for display in the CLI."""
    rows = []
    for name, (module, cls_name, service_type, is_default, test_only) in sorted(REGISTRY.items()):
        if test_only:
            continue
        rows.append(
            {
                "name": name,
                "type": service_type,
                "free": name in FREE_SERVICES,
                "default": is_default,
                "module": module,
                "available": _is_available(name),
            }
        )
    return rows


def get_service_info(name: str) -> dict[str, Any] | None:
    """Get detailed info about a specific service."""
    entry = REGISTRY.get(name.lower())
    if not entry:
        return None

    module_path, class_name, service_type, is_default, _ = entry
    return {
        "name": name,
        "type": service_type,
        "module": module_path,
        "class": class_name,
        "default": is_default,
        "free": name in FREE_SERVICES,
    }


# ---------------------------------------------------------------------------
# Service Discovery - collect all tools/capabilities for LLMs
# ---------------------------------------------------------------------------

def discover_all_capabilities(**service_kwargs: Any) -> list[dict[str, Any]]:
    """Collect all capabilities/tools from all registered services.

    This provides a complete tool list that can be provided to LLMs.
    Each service is instantiated and its capabilities are collected.

    Parameters
    ----------
    **service_kwargs:
        Optional keyword arguments passed to service constructors
        (e.g., model="llama3.2", api_key="xxx")

    Returns
    -------
    List of tool dictionaries with keys: name, description, input_schema, service_type, service_id
    """
    all_tools = []

    for service_name in list_services():
        try:
            service = get_service(service_name, **service_kwargs)
            capabilities = service.capabilities

            for cap in capabilities:
                tool_dict = {
                    "name": cap.name,
                    "description": cap.description,
                    "input_schema": cap.input_schema,
                    "service_type": service.service_type,
                    "service_id": service.service_id,
                }
                all_tools.append(tool_dict)
        except Exception:
            # Skip services that fail to instantiate (missing dependencies, etc.)
            continue

    return all_tools


def discover_capabilities_by_filter(
    service_type: str | None = None,
    name_pattern: str | None = None,
    **service_kwargs: Any
) -> list[dict[str, Any]]:
    """Discover capabilities with filtering support.

    Parameters
    ----------
    service_type:
        Filter by service type (llm, mcp, a2a, builtin)
    name_pattern:
        Filter tool names by pattern (e.g., "file" for file operations)
    **service_kwargs:
        Optional keyword arguments passed to service constructors

    Returns
    -------
    Filtered list of tool dictionaries
    """
    all_tools = discover_all_capabilities(**service_kwargs)

    filtered = all_tools
    if service_type:
        filtered = [t for t in filtered if t["service_type"] == service_type]

    if name_pattern:
        pattern_lower = name_pattern.lower()
        filtered = [t for t in filtered if pattern_lower in t["name"].lower()]

    return filtered


def get_tool_schema_for_llm(**service_kwargs: Any) -> list[dict[str, Any]]:
    """Get tool schemas formatted for LLM function calling.

    Returns tools in the standard format expected by most LLM providers:
    [{"name": str, "description": str, "parameters": dict}, ...]

    Parameters
    ----------
    **service_kwargs:
        Optional keyword arguments passed to service constructors
    """
    capabilities = discover_all_capabilities(**service_kwargs)

    llm_tools = []
    for cap in capabilities:
        tool = {
            "name": cap["name"],
            "description": cap["description"],
            "parameters": cap["input_schema"] or {},
        }
        llm_tools.append(tool)

    return llm_tools

