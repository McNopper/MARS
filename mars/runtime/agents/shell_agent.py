"""MARS Shell Execution Service Agent.

Runs arbitrary shell commands and returns stdout/stderr/exit_code as JSON.

⚠️  Security: this agent runs with the same privileges as the MARS server.
    Use cost=demand in agents.ini so it is only active when explicitly spawned.

Accepted request formats
------------------------
  Plain text:  ls -la
               pytest tests/ -x -q
  JSON:        {"cmd": "ls", "cwd": "/path", "timeout": 10, "env": {"K": "V"}}

Response fields
---------------
  cmd        Original command string
  stdout     Captured standard output (truncated to 64 KB)
  stderr     Captured standard error  (truncated to 64 KB)
  exit_code  Integer exit status
  ok         true iff exit_code == 0
  cwd        Working directory used
  elapsed_s  Wall-clock seconds (float)
  error      Launch error message (only present on OSError)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from typing import Any

from mars.runtime.services.mcp_server import MCPServer


_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB
_DEFAULT_TIMEOUT  = 30         # seconds


def _truncate(text: str, label: str = "") -> str:
    """Truncate *text* to _MAX_OUTPUT_BYTES bytes, appending a note if needed."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return text
    truncated = encoded[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    note = f"\n[{label or 'output'} truncated at {_MAX_OUTPUT_BYTES // 1024} KB]"
    return truncated + note


def _execute(
    cmd: str,
    cwd: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run *cmd* in a subprocess and return a structured result dict."""
    work_dir = cwd or os.getcwd()
    merged_env = {**os.environ}
    if env:
        merged_env.update(env)

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=work_dir,
            env=merged_env,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return {
            "cmd": cmd,
            "stdout": "",
            "stderr": f"[Command timed out after {timeout}s]",
            "exit_code": -1,
            "ok": False,
            "cwd": work_dir,
            "elapsed_s": round(elapsed, 3),
            "error": f"timeout after {timeout}s",
        }
    except OSError as exc:
        elapsed = time.monotonic() - t0
        return {
            "cmd": cmd,
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "ok": False,
            "cwd": work_dir,
            "elapsed_s": round(elapsed, 3),
            "error": str(exc),
        }

    elapsed = time.monotonic() - t0
    return {
        "cmd": cmd,
        "stdout": _truncate(proc.stdout, "stdout"),
        "stderr": _truncate(proc.stderr, "stderr"),
        "exit_code": proc.returncode,
        "ok": proc.returncode == 0,
        "cwd": work_dir,
        "elapsed_s": round(elapsed, 3),
    }


def _dispatch(request: str) -> dict[str, Any]:
    """Parse *request* (plain text or JSON) and execute the shell command."""
    request = request.strip()

    if request.startswith("{"):
        try:
            obj = json.loads(request)
            cmd = str(obj.get("cmd", "")).strip()
            if not cmd:
                return {"ok": False, "error": "missing 'cmd' field"}
            return _execute(
                cmd=cmd,
                cwd=obj.get("cwd"),
                timeout=float(obj.get("timeout", _DEFAULT_TIMEOUT)),
                env=obj.get("env"),
            )
        except json.JSONDecodeError:
            pass  # fall through to plain-text

    if not request:
        return {"ok": False, "error": "empty request"}

    return _execute(cmd=request)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-shell",
        description="MARS shell execution MCP service agent",
    )
    parser.parse_args(argv)

    server = MCPServer("svc.shell", "1.0.0")

    @server.tool(
        "execute_shell",
        "Execute a shell command and return stdout, stderr, and exit code as JSON. "
        "Accepts plain-text commands (e.g. 'ls -la') or JSON objects with optional "
        "cwd, timeout, and env fields.",
    )
    def execute_shell(request: str) -> dict:
        return _dispatch(request)

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
