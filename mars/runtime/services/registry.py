"""MARS agent registry — loads from ../agents/agents.ini.

If agents.ini is missing or has no sections, an empty registry is returned.
Users can add custom agents by adding sections to agents.ini — no Python changes needed.
"""
from __future__ import annotations

import configparser
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mars.constants import CATEGORY_SERVICE, COST_FREE, PROTOCOL_TCP

_INI_PATH = Path(__file__).resolve().parent.parent / "agents" / "agents.ini"

_BUILTIN_COMMAND_MODULES: dict[str, str] = {
    "mars": "mars.client.cli.main",
    "mars-server": "mars.runtime.server.main",
    "mars-llm-wire-agent": "mars.runtime.services.llm_wire_agent",
    "mars-agent-clock": "mars.runtime.agents.clock_agent",
    "mars-agent-profiler": "mars.runtime.agents.profiler_agent",
    "mars-agent-status": "mars.runtime.agents.status_agent",
    "mars-agent-sympy": "mars.runtime.agents.sympy_agent",
    "mars-agent-scipy": "mars.runtime.agents.scipy_agent",
    "mars-agent-file": "mars.runtime.agents.file_agent",
    "mars-agent-url": "mars.runtime.agents.url_agent",
    "mars-agent-ollama": "mars.runtime.agents.ollama_agent",
    "mars-agent-launcher": "mars.runtime.agents.launcher_agent",
    "mars-agent-shell": "mars.runtime.agents.shell_agent",
    "mars-agent-git": "mars.runtime.agents.git_agent",
    "mars-agent-memory": "mars.runtime.agents.memory_agent",
    "mars-agent-session": "mars.runtime.agents.session_agent",
    "mars-agent-scheduler": "mars.runtime.agents.scheduler_agent",
}


def resolve_command(command: str) -> list[str]:
    """Resolve a command string to executable tokens.

    Prefer the configured console-script name when it is on PATH. If it is not
    available (common in editable installs on Windows), fall back to launching
    the matching module with the current Python executable.

    On Windows, batch-script wrappers (.cmd / .bat) are not directly executable
    by ``asyncio.create_subprocess_exec``; they are wrapped in ``cmd.exe /c``.
    """
    # On Windows, shlex's POSIX mode treats backslashes as escape characters,
    # which mangles Windows paths (e.g. C:\Users\norbert → C:Usersnorbert).
    # Use posix=False to preserve backslashes, then strip outer quotes manually
    # (non-POSIX mode keeps the quote characters in the token).
    if sys.platform == "win32":
        raw = shlex.split(command, posix=False)
        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'") else p
                 for p in raw]
    else:
        parts = shlex.split(command)
    if not parts:
        return []
    executable = parts[0]
    resolved = shutil.which(executable)
    if resolved:
        if sys.platform == "win32" and resolved.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", resolved, *parts[1:]]
        return [resolved, *parts[1:]]
    module = _BUILTIN_COMMAND_MODULES.get(executable)
    if module is None:
        return parts
    return [sys.executable, "-m", module, *parts[1:]]


@dataclass
class AgentSpec:
    name: str
    description: str
    command: str          # shell command template; {workdir} is substituted (MCP), or {server}/{workdir} (tcp)
    skills: list[str] = field(default_factory=list)
    category: str = CATEGORY_SERVICE
    cost: str = COST_FREE
    protocol: str = PROTOCOL_TCP


def _load() -> dict[str, AgentSpec]:
    cp = configparser.ConfigParser()
    if not _INI_PATH.exists():
        return {}
    cp.read(_INI_PATH, encoding="utf-8")
    result: dict[str, AgentSpec] = {}
    for name in cp.sections():
        sec = cp[name]
        skills_raw = sec.get("skills", "")
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        result[name] = AgentSpec(
            name=name,
            description=sec.get("description", ""),
            command=sec.get("command", ""),
            skills=skills,
            category=sec.get("category", "service"),
            cost=sec.get("cost", "free"),
            protocol=sec.get("protocol", "tcp"),
        )
    return result


# Load once at import time; call reload() to refresh.
AGENT_REGISTRY: dict[str, AgentSpec] = _load()


def reload() -> None:
    """Reload the registry from agents.ini (useful after edits)."""
    global AGENT_REGISTRY
    AGENT_REGISTRY = _load()


def get(name: str) -> AgentSpec | None:
    return AGENT_REGISTRY.get(name)


def all_specs() -> list[AgentSpec]:
    return list(AGENT_REGISTRY.values())
