from __future__ import annotations

import os
import socket
from datetime import datetime
from pathlib import Path

from mars.common.models import MARSState


def _local_ip() -> str:
    """Return the machine's outbound LAN IP (never 127.0.0.1 / 0.0.0.0)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def _time_ago(dt: datetime) -> str:
    delta = datetime.now() - dt
    secs = int(delta.total_seconds())
    if secs < 5:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"

def _normalize_agent_type(agent_type: str) -> str:
    if agent_type == "CLIBridgeAgent":
        return "HumanUser"
    if agent_type == "ServiceProxyAgent":
        return "Provider"
    return agent_type


def _normalize_echo_mode(value: str) -> str | None:
    v = value.lower().strip()
    if v in ("text", "echo-text", "plain"):
        return "text"
    if v in ("md", "markdown", "echo-md"):
        return "md"
    if v in ("void", "echo-void", "null", "discard", "off"):
        return "void"

    return None


def _running_provider_names(state: MARSState) -> set[str]:
    running: set[str] = set()
    for aid, rec in state.agents.items():
        if rec.agent_type in ("LLMAgent", "EchoBot", "HumanUser", "CLIBridgeAgent"):
            continue
        lowered = aid.lower()
        running.add(lowered)
        if lowered.endswith("-agent"):
            running.add(lowered[:-6])
        if lowered.endswith("-provider"):
            running.add(lowered[:-9])
    return running

def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader – no extra dependencies required."""
    env = Path(path)
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key   = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
