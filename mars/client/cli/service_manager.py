from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Callable

from mars.constants import COST_FREE, GRACE_PERIOD_SECONDS, PROTOCOL_MCP
from mars.runtime.services.registry import AgentSpec, all_specs, resolve_command

def _emit_spawn_status(message: str, status: Callable[[str], None] | None = None) -> None:
    if status is None:
        print(message, flush=True)
    else:
        status(message)


def _launch_service_agent(
    spec: AgentSpec,
    server_addr: str,
    extra_args: list[str] | None = None,
) -> tuple[int, Path]:
    import subprocess

    workdir_path = Path("artifacts") / spec.name
    workdir_path.mkdir(parents=True, exist_ok=True)

    cmd_str = spec.command.format(server=server_addr, workdir=str(workdir_path))
    cmd = resolve_command(cmd_str) + list(extra_args or [])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid, workdir_path


def _stop_service_agents(pids: list[int]) -> None:
    """Send SIGTERM to all service agent subprocesses (synchronous, fire-and-forget)."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


async def _stop_service_agents_async(pids: list[int]) -> None:
    """Terminate service agent subprocesses spawned by the CLI.

    Sends SIGTERM to all processes, waits briefly for them to disconnect
    from the TCP server cleanly, then force-kills any survivors where supported.
    """
    if not pids:
        return
    _stop_service_agents(pids)
    # Grace period: lets agents close their TCP connections before the server is cancelled.
    await asyncio.sleep(GRACE_PERIOD_SECONDS)
    if hasattr(signal, "SIGKILL"):   # not available on Windows
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass


def _auto_spawn_free_agents(
    server_addr: str,
    status: Callable[[str], None] | None = None,
) -> list[int]:
    pids: list[int] = []
    for spec in all_specs():
        if spec.cost != COST_FREE:
            continue
        if spec.protocol == PROTOCOL_MCP:
            # MCP agents are managed by the server via MCPAdapter, not spawned here
            continue
        try:
            pid, _workdir_path = _launch_service_agent(spec, server_addr)
            pids.append(pid)
            _emit_spawn_status(f"[mars-server] Auto-spawned {spec.name} agent (pid {pid})", status)
        except Exception as exc:
            _emit_spawn_status(f"[mars-server] Could not auto-spawn {spec.name}: {exc}", status)
    return pids
