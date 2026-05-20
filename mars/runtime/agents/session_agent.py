"""MARS Session Service Agent.

Saves and restores MARS conversation sessions to/from ~/.mars/sessions/.
Allows naming, listing, loading, and deleting sessions.

Session file format: JSON with fields name, created_at, updated_at,
agents, messages, metadata.

Accepted request formats
------------------------
  save
  save my-feature-work
  list
  load my-feature-work
  rename my-feature-work refactor-session
  delete old-session
  info my-feature-work
  JSON: {"op": "save", "name": "...", "data": {...}}
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mars.runtime.services.mcp_server import MCPServer


_DEFAULT_STORAGE_DIR = Path.home() / ".mars" / "sessions"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _auto_name() -> str:
    return f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _session_path(storage_dir: Path, name: str) -> Path:
    # Sanitize to avoid path traversal
    safe = name.replace("/", "_").replace("\\", "_").replace("..", "_")
    return storage_dir / f"{safe}.json"


def _op_save(
    storage_dir: Path,
    name: str | None,
    data: dict | None,
) -> dict[str, Any]:
    storage_dir.mkdir(parents=True, exist_ok=True)
    session_name = name or _auto_name()
    path = _session_path(storage_dir, session_name)
    now = _now()
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    session = {
        "name": session_name,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "agents": (data or {}).get("agents", existing.get("agents", {})),
        "messages": (data or {}).get("messages", existing.get("messages", [])),
        "metadata": (data or {}).get("metadata", existing.get("metadata", {})),
    }
    path.write_text(json.dumps(session, indent=2, ensure_ascii=False), "utf-8")
    return {"op": "save", "name": session_name, "ok": True}


def _op_list(storage_dir: Path) -> dict[str, Any]:
    if not storage_dir.exists():
        return {"op": "list", "ok": True, "sessions": []}
    sessions = []
    for p in sorted(storage_dir.glob("*.json")):
        try:
            obj = json.loads(p.read_text("utf-8"))
            sessions.append({
                "name": obj.get("name", p.stem),
                "created_at": obj.get("created_at", ""),
                "updated_at": obj.get("updated_at", ""),
            })
        except Exception:
            sessions.append({"name": p.stem})
    return {"op": "list", "ok": True, "sessions": sessions}


def _op_load(storage_dir: Path, name: str) -> dict[str, Any]:
    path = _session_path(storage_dir, name)
    if not path.exists():
        return {"op": "load", "name": name, "ok": False, "error": f"session {name!r} not found"}
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception as exc:
        return {"op": "load", "name": name, "ok": False, "error": str(exc)}
    return {"op": "load", "name": name, "ok": True, "data": data}


def _op_rename(storage_dir: Path, old_name: str, new_name: str) -> dict[str, Any]:
    old_path = _session_path(storage_dir, old_name)
    new_path = _session_path(storage_dir, new_name)
    if not old_path.exists():
        return {"op": "rename", "ok": False, "error": f"session {old_name!r} not found"}
    if new_path.exists():
        return {"op": "rename", "ok": False, "error": f"session {new_name!r} already exists"}
    try:
        data = json.loads(old_path.read_text("utf-8"))
        data["name"] = new_name
        data["updated_at"] = _now()
        new_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        old_path.unlink()
    except Exception as exc:
        return {"op": "rename", "ok": False, "error": str(exc)}
    return {"op": "rename", "old_name": old_name, "new_name": new_name, "ok": True}


def _op_delete(storage_dir: Path, name: str) -> dict[str, Any]:
    path = _session_path(storage_dir, name)
    if not path.exists():
        return {"op": "delete", "name": name, "ok": False, "error": f"session {name!r} not found"}
    try:
        path.unlink()
    except Exception as exc:
        return {"op": "delete", "name": name, "ok": False, "error": str(exc)}
    return {"op": "delete", "name": name, "ok": True}


def _op_info(storage_dir: Path, name: str) -> dict[str, Any]:
    path = _session_path(storage_dir, name)
    if not path.exists():
        return {"op": "info", "name": name, "ok": False, "error": f"session {name!r} not found"}
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception as exc:
        return {"op": "info", "name": name, "ok": False, "error": str(exc)}
    return {
        "op": "info",
        "name": data.get("name", name),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
        "message_count": len(data.get("messages", [])),
        "agent_count": len(data.get("agents", {})),
        "ok": True,
    }


def _dispatch(storage_dir: Path, request: str) -> dict[str, Any]:
    request = request.strip()

    if request.startswith("{"):
        try:
            obj = json.loads(request)
            op = str(obj.get("op", "")).lower()
            name = obj.get("name")
            data = obj.get("data")
            if op == "save":
                return _op_save(storage_dir, name, data)
            if op == "load":
                return _op_load(storage_dir, name or "")
            if op == "list":
                return _op_list(storage_dir)
            if op == "rename":
                return _op_rename(storage_dir, name or "", obj.get("new_name", ""))
            if op in ("delete", "remove"):
                return _op_delete(storage_dir, name or "")
            if op == "info":
                return _op_info(storage_dir, name or "")
            return {"op": op, "ok": False, "error": f"unknown op: {op!r}"}
        except json.JSONDecodeError:
            pass

    parts = request.split()
    if not parts:
        return {"op": "unknown", "ok": False, "error": "empty request"}

    verb = parts[0].lower()

    if verb == "save":
        name = parts[1] if len(parts) > 1 else None
        return _op_save(storage_dir, name, None)

    if verb == "list":
        return _op_list(storage_dir)

    if verb == "load":
        name = parts[1] if len(parts) > 1 else ""
        return _op_load(storage_dir, name)

    if verb == "rename":
        old = parts[1] if len(parts) > 1 else ""
        new = parts[2] if len(parts) > 2 else ""
        return _op_rename(storage_dir, old, new)

    if verb in ("delete", "remove"):
        name = parts[1] if len(parts) > 1 else ""
        return _op_delete(storage_dir, name)

    if verb == "info":
        name = parts[1] if len(parts) > 1 else ""
        return _op_info(storage_dir, name)

    return {"op": verb, "ok": False,
            "error": f"unknown verb: {verb!r}. Use: save, load, list, rename, delete, info"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-session",
        description="MARS session management MCP service agent",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Directory for session files (default: ~/.mars/sessions/)",
    )
    args = parser.parse_args(argv)
    storage_dir = Path(args.storage_dir) if args.storage_dir else _DEFAULT_STORAGE_DIR

    server = MCPServer("svc.session", "1.0.0")

    @server.tool(
        "session",
        "Save, load, list, rename, delete, and inspect conversation sessions. "
        "Use 'save [name]', 'load <name>', 'list', 'rename <old> <new>', "
        "'delete <name>', 'info <name>'. Also accepts JSON objects.",
    )
    def session(request: str) -> dict:
        return _dispatch(storage_dir, request)

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
