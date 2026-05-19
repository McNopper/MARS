"""MARS agent registry — loads from agents.ini in this directory.

If agents.ini is missing or has no sections, an empty registry is returned.
Users can add custom agents by adding sections to agents.ini — no Python changes needed.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

_INI_PATH = Path(__file__).parent / "agents.ini"


@dataclass
class AgentSpec:
    name: str
    description: str
    command: str          # shell command template; {workdir} is substituted (MCP), or {server}/{workdir} (tcp)
    skills: list[str] = field(default_factory=list)
    category: str = "service"
    cost: str = "free"
    protocol: str = "tcp"  # "tcp" (legacy wire protocol) or "mcp" (MCP stdio)


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
