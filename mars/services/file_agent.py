"""MARS File I/O Service Agent — sandboxed file system operations.

All paths are resolved relative to the agent's working directory
(default: ``artifacts/fileio/``).  Absolute paths and ``..`` traversal
are rejected so the agent cannot escape its sandbox.

Supported operations (auto-detected or explicit JSON command)
-------------------------------------------------------------
  read   <path>                Read a file and return its content
  write  <path> <content>      Write (or overwrite) a file
  append <path> <content>      Append to a file (creates it if absent)
  list   [dir]                 List files / sub-directories in a directory
  delete <path>                Delete a file
  exists <path>                Check whether a path exists
  mkdir  <path>                Create a directory (including parents)

Input formats accepted
----------------------
  Plain text:  ``read notes.txt``
               ``write notes.txt Hello, world!``
  JSON object: ``{"op": "read", "path": "notes.txt"}``
               ``{"op": "write", "path": "out.txt", "content": "data"}``

Response fields (JSON artifact)
--------------------------------
  op        Operation that was performed
  path      Normalised path (relative to workdir)
  ok        true on success, false on error
  content   File content as a UTF-8 string (read / list)
  entries   List of entry names (list)
  size      File size in bytes (read / write / exists)
  error     Error message (only present on failure)
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

from mars.services.mcp_server import MCPServer


_DEFAULT_WORKDIR = Path("artifacts") / "fileio"
_MAX_READ_BYTES = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

def _safe_path(workdir: Path, user_path: str) -> Path | None:
    """Resolve *user_path* inside *workdir*; return None if it escapes."""
    try:
        resolved = (workdir / user_path).resolve()
        workdir_resolved = workdir.resolve()
        resolved.relative_to(workdir_resolved)  # raises ValueError if outside
        return resolved
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------

def _op_read(workdir: Path, path: str) -> dict[str, Any]:
    target = _safe_path(workdir, path)
    if target is None:
        return {"op": "read", "path": path, "ok": False, "error": "path escapes sandbox"}
    if not target.exists():
        return {"op": "read", "path": path, "ok": False, "error": "file not found"}
    if not target.is_file():
        return {"op": "read", "path": path, "ok": False, "error": "path is not a file"}
    size = target.stat().st_size
    if size > _MAX_READ_BYTES:
        return {"op": "read", "path": path, "ok": False,
                "error": f"file too large ({size} bytes; limit {_MAX_READ_BYTES})"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        data = base64.b64encode(target.read_bytes()).decode("ascii")
        return {"op": "read", "path": path, "ok": True, "size": size,
                "encoding": "base64", "content": data}
    return {"op": "read", "path": path, "ok": True, "size": size, "content": content}


def _op_write(workdir: Path, path: str, content: str, append: bool = False) -> dict[str, Any]:
    target = _safe_path(workdir, path)
    if target is None:
        return {"op": "write", "path": path, "ok": False, "error": "path escapes sandbox"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with target.open("a", encoding="utf-8") as fh:
                fh.write(content)
        else:
            target.write_text(content, encoding="utf-8")
        return {"op": "append" if append else "write", "path": path, "ok": True,
                "size": target.stat().st_size}
    except OSError as exc:
        return {"op": "write", "path": path, "ok": False, "error": str(exc)}


def _op_list(workdir: Path, path: str = ".") -> dict[str, Any]:
    target = _safe_path(workdir, path)
    if target is None:
        return {"op": "list", "path": path, "ok": False, "error": "path escapes sandbox"}
    if not target.exists():
        return {"op": "list", "path": path, "ok": False, "error": "directory not found"}
    if not target.is_dir():
        return {"op": "list", "path": path, "ok": False, "error": "path is not a directory"}
    entries = []
    for entry in sorted(target.iterdir()):
        kind = "dir" if entry.is_dir() else "file"
        info: dict[str, Any] = {"name": entry.name, "type": kind}
        if kind == "file":
            info["size"] = entry.stat().st_size
        entries.append(info)
    return {"op": "list", "path": path, "ok": True, "entries": entries}


def _op_delete(workdir: Path, path: str) -> dict[str, Any]:
    target = _safe_path(workdir, path)
    if target is None:
        return {"op": "delete", "path": path, "ok": False, "error": "path escapes sandbox"}
    if not target.exists():
        return {"op": "delete", "path": path, "ok": False, "error": "file not found"}
    try:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"op": "delete", "path": path, "ok": True}
    except OSError as exc:
        return {"op": "delete", "path": path, "ok": False, "error": str(exc)}


def _op_exists(workdir: Path, path: str) -> dict[str, Any]:
    target = _safe_path(workdir, path)
    if target is None:
        return {"op": "exists", "path": path, "ok": False, "error": "path escapes sandbox"}
    exists = target.exists()
    result: dict[str, Any] = {"op": "exists", "path": path, "ok": True, "exists": exists}
    if exists:
        result["type"] = "dir" if target.is_dir() else "file"
        if target.is_file():
            result["size"] = target.stat().st_size
    return result


def _op_mkdir(workdir: Path, path: str) -> dict[str, Any]:
    target = _safe_path(workdir, path)
    if target is None:
        return {"op": "mkdir", "path": path, "ok": False, "error": "path escapes sandbox"}
    try:
        target.mkdir(parents=True, exist_ok=True)
        return {"op": "mkdir", "path": path, "ok": True}
    except OSError as exc:
        return {"op": "mkdir", "path": path, "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Natural-language preprocessing
# ---------------------------------------------------------------------------

def _normalize_file_request(text: str) -> str:
    """Translate natural-language file commands to the canonical keyword form.

    Examples
    --------
    "read the file notes.txt"          → "read notes.txt"
    "write Hello World to notes.txt"   → "write notes.txt Hello World"
    "save Hello World as notes.txt"    → "write notes.txt Hello World"
    "append More text to notes.txt"    → "append notes.txt More text"
    "list files in data/"              → "list data/"
    "delete the file notes.txt"        → "delete notes.txt"
    "check if notes.txt exists"        → "exists notes.txt"
    "create directory logs/"           → "mkdir logs/"
    """
    t = text.strip().rstrip("?!.")

    # Already a JSON or known keyword — pass through unchanged.
    if t.startswith("{"):
        return t
    first = t.split()[0].lower() if t.split() else ""
    if first in ("read", "write", "append", "list", "ls", "dir",
                 "delete", "rm", "remove", "exists", "exist", "mkdir", "md"):
        return t

    # read / show / open / cat
    m = re.match(
        r"^(?:read|show|open|display|cat|print|get|load)\s+"
        r"(?:the\s+)?(?:contents?\s+of\s+|file\s+)?(\S+)",
        t, re.I,
    )
    if m:
        return f"read {m.group(1)}"

    # write <content> to <file>
    m = re.match(r"^write\s+(.+?)\s+to\s+(\S+)$", t, re.I)
    if m:
        return f"write {m.group(2)} {m.group(1)}"

    # save <content> as/to <file>
    m = re.match(r"^save\s+(.+?)\s+(?:as|to)\s+(\S+)$", t, re.I)
    if m:
        return f"write {m.group(2)} {m.group(1)}"

    # append <content> to <file>
    m = re.match(r"^append\s+(.+?)\s+to\s+(\S+)$", t, re.I)
    if m:
        return f"append {m.group(2)} {m.group(1)}"

    # list files [in <dir>]
    m = re.match(
        r"^(?:list|show|ls)\s+(?:files?\s+)?(?:in\s+|inside\s+|of\s+)?(.+)",
        t, re.I,
    )
    if m:
        return f"list {m.group(1).strip()}"

    # delete / remove
    m = re.match(
        r"^(?:delete|remove|erase)\s+(?:the\s+)?(?:file\s+)?(\S+)", t, re.I
    )
    if m:
        return f"delete {m.group(1)}"

    # check if / does … exist
    m = re.match(
        r"^(?:check\s+(?:if\s+|whether\s+)|does\s+)(\S+)\s+exist", t, re.I
    )
    if m:
        return f"exists {m.group(1)}"

    # create / make directory
    m = re.match(
        r"^(?:create|make)\s+(?:a\s+)?(?:directory|folder|dir)\s+(\S+)", t, re.I
    )
    if m:
        return f"mkdir {m.group(1)}"

    return t


# ---------------------------------------------------------------------------
# Request dispatcher
# ---------------------------------------------------------------------------

def _dispatch(workdir: Path, text: str) -> dict[str, Any]:
    """Parse *text* (plain or JSON) and dispatch to the right handler."""
    text = text.strip()

    # Try JSON object first
    if text.startswith("{"):
        try:
            cmd = json.loads(text)
            op = str(cmd.get("op", "")).lower()
            path = str(cmd.get("path", "")).strip()
            content = str(cmd.get("content", ""))
            if op == "read":
                return _op_read(workdir, path)
            if op == "write":
                return _op_write(workdir, path, content)
            if op == "append":
                return _op_write(workdir, path, content, append=True)
            if op == "list":
                return _op_list(workdir, path or ".")
            if op == "delete":
                return _op_delete(workdir, path)
            if op == "exists":
                return _op_exists(workdir, path)
            if op == "mkdir":
                return _op_mkdir(workdir, path)
            return {"op": op or "unknown", "ok": False,
                    "error": f"unknown operation: {op!r}"}
        except json.JSONDecodeError:
            pass  # fall through to plain-text parsing

    # Plain-text parsing: "op path [content...]"
    parts = text.split(None, 2)
    if not parts:
        return {"op": "unknown", "ok": False, "error": "empty request"}

    op = parts[0].lower()
    path = parts[1] if len(parts) > 1 else "."
    content = parts[2] if len(parts) > 2 else ""

    if op == "read":
        return _op_read(workdir, path)
    if op == "write":
        return _op_write(workdir, path, content)
    if op == "append":
        return _op_write(workdir, path, content, append=True)
    if op in ("list", "ls", "dir"):
        return _op_list(workdir, path)
    if op in ("delete", "rm", "remove"):
        return _op_delete(workdir, path)
    if op in ("exists", "exist"):
        return _op_exists(workdir, path)
    if op in ("mkdir", "md"):
        return _op_mkdir(workdir, path)

    return {"op": op, "ok": False, "error": f"unknown operation: {op!r}. "
            "Supported: read, write, append, list, delete, exists, mkdir"}


# ---------------------------------------------------------------------------
# Agent wire loop
# ---------------------------------------------------------------------------

async def run_agent(server: str, workdir: str | None = None) -> None:
    from mars.services.service_utils import build_hello, run_wire_agent
    work = Path(workdir) if workdir else _DEFAULT_WORKDIR
    work.mkdir(parents=True, exist_ok=True)

    await run_wire_agent(
        server,
        build_hello("svc.file@1", [
            "file", "read", "write", "fileio", "storage", "filesystem",
            "list", "delete", "append", "mkdir",
        ]),
        lambda text: _dispatch(work, text),
        "file_result.json",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-file",
        description="MARS file I/O MCP service agent",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Sandbox working directory (default: artifacts/fileio/)",
    )
    args = parser.parse_args(argv)
    work = Path(args.workdir) if args.workdir else _DEFAULT_WORKDIR
    work.mkdir(parents=True, exist_ok=True)

    server = MCPServer("svc.file", "1.0.0")

    @server.tool(
        "file_io",
        "Sandboxed file I/O: read, write, append, list, delete, exists, mkdir. "
        "Accepts plain-text commands (e.g. 'read notes.txt') or JSON objects.",
    )
    def file_io(request: str) -> dict:
        return _normalize_and_dispatch(work, request)

    asyncio.run(server.run())


def _normalize_and_dispatch(work: Path, text: str) -> dict:
    return _dispatch(work, text)


if __name__ == "__main__":
    main()
