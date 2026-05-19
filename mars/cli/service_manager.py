from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Callable

from mars.services.registry import AgentSpec, all_specs

def _emit_spawn_status(message: str, status: Callable[[str], None] | None = None) -> None:
    if status is None:
        print(message, flush=True)
    else:
        status(message)


def _launch_service_agent(
    spec: AgentSpec,
    server_addr: str,
    extra_args: list[str] | None = None,
) -> tuple[int, Path, bool]:
    import shlex
    import subprocess

    workdir_path = Path("artifacts") / spec.name
    workdir_path.mkdir(parents=True, exist_ok=True)

    cmd_str = spec.command.format(server=server_addr, workdir=str(workdir_path))
    cmd = shlex.split(cmd_str) + list(extra_args or [])

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid, workdir_path, False
    except FileNotFoundError:
        ep = cmd[0]
        module = "mars.services." + ep.replace("mars-agent-", "").replace("-", "_") + "_agent"
        fallback_cmd = [sys.executable, "-m", module] + cmd[1:]
        proc = subprocess.Popen(
            fallback_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid, workdir_path, True


def _stop_service_agents(pids: list[int]) -> None:
    """Send SIGTERM to all service agent subprocesses (synchronous, fire-and-forget)."""
    import signal
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone


async def _stop_service_agents_async(pids: list[int]) -> None:
    """Terminate service agent subprocesses spawned by the CLI.

    Sends SIGTERM to all processes, waits briefly for them to disconnect
    from the TCP server cleanly, then force-kills any survivors on Unix.
    """
    import signal
    if not pids:
        return
    _stop_service_agents(pids)
    # Grace period: lets agents close their TCP connections before the server is cancelled.
    await asyncio.sleep(1.5)
    if sys.platform != "win32":
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass  # already gone


def _auto_spawn_free_agents(
    server_addr: str,
    status: Callable[[str], None] | None = None,
) -> list[int]:
    pids: list[int] = []
    for spec in all_specs():
        if spec.cost != "free":
            continue
        if spec.protocol == "mcp":
            # MCP agents are managed by the server via MCPAdapter, not spawned here
            continue
        try:
            pid, _workdir_path, via_module = _launch_service_agent(spec, server_addr)
            pids.append(pid)
            if via_module:
                _emit_spawn_status(f"[mars-server] Auto-spawned {spec.name} via python -m (pid {pid})", status)
            else:
                _emit_spawn_status(f"[mars-server] Auto-spawned {spec.name} agent (pid {pid})", status)
        except Exception as exc:
            _emit_spawn_status(f"[mars-server] Could not auto-spawn {spec.name}: {exc}", status)
    return pids
