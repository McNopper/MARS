"""MARS Git Service Agent.

Exposes common git operations as MCP tools so LLM agents can read diffs,
check status, commit, and browse history without direct shell access.

Uses the ``gitpython`` library — no external ``git`` binary on PATH required
(gitpython bundles its own git discovery, though a system git is still used
under the hood when available).

Accepted request formats
------------------------
  Plain:  diff
          diff --staged
          status
          log -5
          add src/foo.py
          commit Fix the bug
          branch feature/new-thing
          blame src/main.py

  JSON:   {"op": "diff", "args": ["--staged"], "cwd": "/opt/project"}
          {"op": "log",  "args": ["-20", "--oneline"]}

Response fields
---------------
  op         The git sub-command that was run
  output     Combined stdout + stderr (truncated to 64 KB)
  ok         true iff exit_code == 0
  exit_code  Integer exit status
  error      Error message if the operation could not be run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from mars.runtime.services.mcp_server import MCPServer

try:
    import git as _git
    _GIT_AVAILABLE = True
except ImportError:
    _GIT_AVAILABLE = False


_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB

_VALID_OPS = {
    "diff", "status", "log", "add", "commit",
    "branch", "checkout", "blame", "show", "fetch",
    "pull", "push", "stash", "tag", "reset", "revert",
}


def _truncate(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return text
    return encoded[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace") + "\n[output truncated]"


def _run_git(op: str, args: list[str], cwd: str | None = None) -> dict[str, Any]:
    """Run ``git <op> [args…]`` via gitpython and return a structured dict."""
    if not _GIT_AVAILABLE:
        return {
            "op": op, "output": "", "ok": False, "exit_code": -1,
            "error": "gitpython not installed — run: pip install gitpython",
        }

    work_dir = cwd or os.getcwd()
    try:
        repo = _git.Repo(work_dir, search_parent_directories=True)
    except _git.InvalidGitRepositoryError:
        return {"op": op, "output": "", "ok": False, "exit_code": 128,
                "error": f"not a git repository: {work_dir}"}
    except Exception as exc:
        return {"op": op, "output": "", "ok": False, "exit_code": -1, "error": str(exc)}

    try:
        status, stdout, stderr = repo.git.execute(
            ["git", op] + args,
            with_extended_output=True,
            with_exceptions=False,
        )
        combined = stdout + (("\n" + stderr) if stderr.strip() else "")
        return {
            "op": op,
            "output": _truncate(combined),
            "ok": status == 0,
            "exit_code": status,
        }
    except Exception as exc:
        return {"op": op, "output": "", "ok": False, "exit_code": -1, "error": str(exc)}


def _dispatch(request: str) -> dict[str, Any]:
    """Parse *request* (plain text or JSON) and dispatch to the right git handler."""
    request = request.strip()

    if request.startswith("{"):
        try:
            obj = json.loads(request)
            op = str(obj.get("op", "")).strip()
            args = list(obj.get("args", []))
            cwd = obj.get("cwd")
            if not op:
                return {"op": "unknown", "ok": False, "error": "missing 'op' field"}
            return _run_git(op, args, cwd)
        except json.JSONDecodeError:
            pass

    # Strip "git " prefix if present
    text = request.strip()
    if text.lower().startswith("git "):
        text = text[4:].lstrip()

    parts = text.split(None, 1)
    if not parts:
        return {"op": "unknown", "ok": False, "error": "empty request"}

    op = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    extra_args = rest.split() if rest else []

    if op not in _VALID_OPS:
        return {
            "op": op,
            "ok": False,
            "error": (
                f"unsupported operation: {op!r}. "
                f"Supported: {', '.join(sorted(_VALID_OPS))}"
            ),
        }

    # Default log count if no args provided
    if op == "log" and not extra_args:
        extra_args = ["-10", "--oneline"]

    # Commit needs the message as a -m arg
    if op == "commit" and rest:
        extra_args = ["-m", rest]

    return _run_git(op, extra_args)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-git",
        description="MARS git operations MCP service agent",
    )
    parser.parse_args(argv)

    server = MCPServer("svc.git", "1.0.0")

    @server.tool(
        "git_operation",
        "Run a git operation (diff, status, log, add, commit, branch, blame, show, "
        "checkout, …) and return the output as JSON. "
        "Accepts plain-text ('diff --staged', 'log -10') or JSON "
        "({'op': 'log', 'args': ['-5', '--oneline'], 'cwd': '/path'}).",
    )
    def git_operation(request: str) -> dict:
        return _dispatch(request)

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
