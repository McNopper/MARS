from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from mars.common.constants import COST_FREE, GRACE_PERIOD_SECONDS, PROTOCOL_MCP
from mars.server.services.registry import AgentSpec, all_specs, resolve_command

# Map well-known entry-point script names to their ``python -m <module>`` equivalents.
# This ensures subprocesses always run in the correct interpreter even when the
# console_scripts wrapper is not on PATH (e.g., on Windows or in editable installs).
_SCRIPT_TO_MODULE: dict[str, str] = {
    "mars-agent-status":    "mars.server.agents.status_agent",
    "mars-agent-launcher":  "mars.server.agents.launcher_agent",
    "mars-llm-wire-agent":  "mars.server.services.llm_wire_agent",
}


def _emit_spawn_status(message: str, status: Callable[[str], None] | None = None) -> None:
    if status is None:
        print(message, flush=True)
    else:
        status(message)


def _launch_provider(
    spec: AgentSpec,
    server_addr: str,
    extra_args: list[str] | None = None,
) -> tuple[int, Path]:
    workdir_path = Path("artifacts") / spec.name
    workdir_path.mkdir(parents=True, exist_ok=True)

    cmd_str = spec.command.format(server=server_addr, workdir=str(workdir_path))
    raw_cmd = resolve_command(cmd_str) + list(extra_args or [])

    # Expand known entry-point scripts to ``[sys.executable, "-m", module]``
    # so the subprocess always runs under the same interpreter.
    if raw_cmd and raw_cmd[0] in _SCRIPT_TO_MODULE:
        module = _SCRIPT_TO_MODULE[raw_cmd[0]]
        cmd = [sys.executable, "-m", module] + raw_cmd[1:]
    else:
        cmd = raw_cmd

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid, workdir_path


def _stop_providers(pids: list[int]) -> None:
    """Send SIGTERM to all provider subprocesses (synchronous, fire-and-forget)."""
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGTERM)


async def _stop_providers_async(pids: list[int]) -> None:
    """Terminate provider subprocesses spawned by the CLI.

    Sends SIGTERM to all processes, waits briefly for them to disconnect
    from the TCP server cleanly, then force-kills any survivors where supported.
    """
    if not pids:
        return
    _stop_providers(pids)
    # Grace period: lets providers close their TCP connections before the server is cancelled.
    await asyncio.sleep(GRACE_PERIOD_SECONDS)
    if hasattr(signal, "SIGKILL"):   # not available on Windows
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGKILL)


def _auto_spawn_free_providers(
    server_addr: str,
    status: Callable[[str], None] | None = None,
) -> list[int]:
    pids: list[int] = []
    for spec in all_specs():
        if spec.cost != COST_FREE:
            continue
        if spec.protocol == PROTOCOL_MCP:
            # MCP providers are managed by the server via MCPAdapter, not spawned here
            continue
        try:
            pid, _workdir_path = _launch_provider(spec, server_addr)
            pids.append(pid)
            _emit_spawn_status(f"[mars-server] Auto-spawned {spec.name} provider (pid {pid})", status)
        except Exception as exc:
            _emit_spawn_status(f"[mars-server] Could not auto-spawn {spec.name}: {exc}", status)
    return pids
