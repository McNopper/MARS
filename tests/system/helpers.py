"""Shared helpers for MARS system tests.

Import as:
    from tests.system import helpers
    # or
    import tests.system.helpers as helpers
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from mars.server.main import MARSServer
from mars.common.models import MARSState


async def start_server(port: int) -> MARSServer:
    """Start an in-process MARS server on *port* and return it once ready."""
    state = MARSState()
    server = MARSServer(state)
    ready: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    asyncio.create_task(server.serve("127.0.0.1", port, ready_future=ready))
    await asyncio.wait_for(ready, timeout=5.0)
    return server


async def connect(
    port: int,
    name: str,
    role: str = "human",
    agent_type: str | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Open a TCP connection to the MARS server and send a hello frame."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hello: dict = {"t": "hello", "role": role, "name": name}
    if agent_type:
        hello["agent_type"] = agent_type
    writer.write((json.dumps(hello) + "\n").encode())
    await writer.drain()
    return reader, writer


async def read_until(
    reader: asyncio.StreamReader,
    *,
    t: str,
    timeout: float = 10.0,
    **match_fields,
) -> dict:
    """Read frames until one with the expected ``t`` field arrives.

    Pass extra keyword arguments to require additional field matches, e.g.::

        await read_until(reader, t="spawn", agent_type="LLMAgent")
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for event t={t!r} {match_fields}")
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        ev = json.loads(raw.decode())
        if ev.get("t") == t and all(ev.get(k) == v for k, v in match_fields.items()):
            return ev


async def read_any(
    reader: asyncio.StreamReader,
    *,
    timeout: float = 15.0,
) -> list[dict]:
    """Read events until *timeout*; stops early once a chat/msg event arrives."""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=min(remaining, 1.0))
            events.append(json.loads(raw.decode()))
        except asyncio.TimeoutError:
            if any(e.get("t") in ("chat", "msg") for e in events):
                break
    return events


async def collect_n(
    reader: asyncio.StreamReader,
    *,
    t: str,
    n: int,
    timeout: float = 20.0,
) -> list[dict]:
    """Collect exactly *n* events of type *t* from the stream."""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(events) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Only got {len(events)}/{n} events of type t={t!r} before timeout"
            )
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        ev = json.loads(raw.decode())
        if ev.get("t") == t:
            events.append(ev)
    return events


async def read_initial_events(
    reader: asyncio.StreamReader,
    *,
    timeout: float = 5.0,
) -> list[dict]:
    """Read all events up to and including the ``welcome`` event."""
    events: list[dict] = []
    while True:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=timeout)
            ev = json.loads(raw.decode())
            events.append(ev)
            if ev.get("t") == "welcome":
                break
        except asyncio.TimeoutError:
            break
    return events


def send_msg(writer: asyncio.StreamWriter, target: str, text: str) -> None:
    """Write a ``msg`` frame to the server (fire and forget; caller must drain)."""
    writer.write((json.dumps({"t": "msg", "target": target, "text": text}) + "\n").encode())


def send_cmd(writer: asyncio.StreamWriter, text: str) -> None:
    """Write a ``cmd`` frame to the server (fire and forget; caller must drain)."""
    writer.write((json.dumps({"t": "cmd", "text": text}) + "\n").encode())


def send_struct_cmd(writer: asyncio.StreamWriter, cmd: str, **fields) -> None:
    """Write a structured ``{"t":"cmd","cmd":...}`` frame (caller must drain)."""
    frame: dict = {"t": "cmd", "cmd": cmd, **fields}
    writer.write((json.dumps(frame) + "\n").encode())


async def connect_agent(
    port: int,
    name: str,
    skills: list[str],
    agent_type: str = "Provider",
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect a provider/agent session that advertises *skills* in its hello."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hello = {
        "t": "hello",
        "role": "agent",
        "name": name,
        "agent_type": agent_type,
        "skills": skills,
    }
    writer.write((json.dumps(hello) + "\n").encode())
    await writer.drain()
    return reader, writer


def spawn_llm_agent(
    port: int,
    provider: str = "mock-tool",
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """Spawn an ``llm_wire_agent`` subprocess for the given *provider*."""
    cmd = [
        sys.executable, "-m", "mars.server.services.llm_wire_agent",
        "--server", f"127.0.0.1:{port}",
        "--provider", provider,
    ] + (extra_args or [])
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Environment / skip guards
# ---------------------------------------------------------------------------

def copilot_available() -> bool:
    """Return True when a GitHub OAuth token is available via gh auth login."""
    from mars.server.services.llm.copilot import _get_token
    try:
        return bool(_get_token())
    except Exception:
        return False


def ollama_reachable(host: str = "http://localhost:11434") -> bool:
    """Return True when an Ollama server is reachable."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def first_ollama_model(host: str = "http://localhost:11434") -> str:
    """Return an installed Ollama model name, preferring a lightweight one.

    Heavy models (e.g. 20GB+) can take minutes to load on first call and make
    live tests time out, so prefer known-small models when available before
    falling back to whatever is installed first.
    """
    # Smallest / fastest-loading models first.
    _PREFERRED = ("llama3.2", "qwen2.5:7b", "mistral", "phi3", "gemma2:2b")
    try:
        import urllib.request
        import json as _json
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as r:
            data = _json.loads(r.read())
        models = data.get("models", [])
        names = [m["name"] for m in models]
        if names:
            for pref in _PREFERRED:
                for name in names:
                    if name == pref or name.startswith(pref + ":") or name.split(":")[0] == pref:
                        return name
            # No preferred match — pick the smallest by reported size.
            with_size = [m for m in models if isinstance(m.get("size"), (int, float))]
            if with_size:
                return min(with_size, key=lambda m: m["size"])["name"]
            return names[0]
    except Exception:
        pass
    return "llama3.2"


def builtin_agent_available(cmd_name: str) -> bool:
    """Return True if the named built-in MARS agent can be launched.

    Mirrors the logic in ``registry.resolve_command``: the console-script name
    is preferred when it is on PATH, but built-in agents always have a
    ``python -m <module>`` fallback registered in ``_BUILTIN_COMMAND_MODULES``.
    So for any command listed there this function always returns True.
    """
    import shutil
    if shutil.which(cmd_name):
        return True
    from mars.server.services.registry import _BUILTIN_COMMAND_MODULES
    return cmd_name in _BUILTIN_COMMAND_MODULES


def anthropic_available() -> bool:
    """Return True when ``ANTHROPIC_API_KEY`` is set and the SDK is installed."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def github_mcp_binary() -> "Path | None":
    """Return the path to the GitHub MCP server binary, or None if not found."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "bin" / "github-mcp-server.exe",
        Path(__file__).resolve().parent.parent.parent / "bin" / "github-mcp-server",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def npx_available() -> bool:
    """Return True when ``npx`` is on PATH (Node.js required for filesystem MCP)."""
    import shutil
    return shutil.which("npx") is not None


def mcp_sdk_available() -> bool:
    """Return True when the official ``mcp`` SDK (FastMCP) is importable.

    ``mcp`` is a declared core dependency, but a partial/editable install may
    lack it; the native filesystem agent subprocess needs it to start.
    """
    import importlib.util
    return importlib.util.find_spec("mcp") is not None
