"""MARS Memory Service Agent.

Persists key-value facts across MARS sessions in ~/.mars/memory.json.
LLM agents can call this to remember information, recall stored facts,
or forget entries.

Storage format (~/.mars/memory.json)
-------------------------------------
  {
    "key": {
      "value": "...",
      "created_at": "2025-01-01T00:00:00",
      "updated_at": "2025-01-01T00:00:00"
    }
  }

Accepted request formats
------------------------
  remember project: MARS multi-agent platform
  remember The user prefers Python 3.11
  recall project
  recall
  forget project
  forget all
  JSON: {"op": "remember", "key": "x", "value": "y"}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mars.runtime.services.mcp_server import MCPServer


_DEFAULT_STORAGE_DIR = Path.home() / ".mars"
_MEMORY_FILENAME = "memory.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load(storage_dir: Path) -> dict[str, Any]:
    path = storage_dir / _MEMORY_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return {}


def _save(storage_dir: Path, data: dict[str, Any]) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / _MEMORY_FILENAME).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), "utf-8"
    )


def _short_key() -> str:
    return uuid.uuid4().hex[:8]


def _op_remember(
    storage_dir: Path,
    key: str | None,
    value: str,
) -> dict[str, Any]:
    data = _load(storage_dir)
    now = _now()
    if not key:
        key = _short_key()
    entry = data.get(key, {})
    entry["value"] = value
    entry.setdefault("created_at", now)
    entry["updated_at"] = now
    data[key] = entry
    _save(storage_dir, data)
    return {"op": "remember", "key": key, "value": value, "ok": True}


def _op_recall(storage_dir: Path, key: str | None) -> dict[str, Any]:
    data = _load(storage_dir)
    if key:
        entry = data.get(key)
        if entry is None:
            return {"op": "recall", "key": key, "ok": False, "error": f"key {key!r} not found"}
        return {"op": "recall", "key": key, "value": entry["value"], "ok": True}
    # Return all
    all_facts = [{"key": k, **v} for k, v in data.items()]
    return {"op": "recall", "ok": True, "count": len(all_facts), "facts": all_facts}


def _op_forget(storage_dir: Path, key: str) -> dict[str, Any]:
    key_lower = key.strip().lower()
    if key_lower in ("all", "everything", "clear"):
        _save(storage_dir, {})
        return {"op": "forget", "ok": True, "cleared": True}
    data = _load(storage_dir)
    if key not in data:
        return {"op": "forget", "key": key, "ok": False, "error": f"key {key!r} not found"}
    del data[key]
    _save(storage_dir, data)
    return {"op": "forget", "key": key, "ok": True}


def _dispatch(storage_dir: Path, request: str) -> dict[str, Any]:
    """Parse *request* and route to the right memory handler."""
    request = request.strip()

    if request.startswith("{"):
        try:
            obj = json.loads(request)
            op = str(obj.get("op", "")).lower()
            key = obj.get("key") or None
            value = str(obj.get("value", ""))
            if op == "remember":
                return _op_remember(storage_dir, key, value)
            if op == "recall":
                return _op_recall(storage_dir, key)
            if op in ("forget", "delete", "clear"):
                return _op_forget(storage_dir, key or "all")
            if op == "list":
                return _op_recall(storage_dir, None)
            return {"op": op, "ok": False, "error": f"unknown op: {op!r}"}
        except json.JSONDecodeError:
            pass

    parts = request.split(None, 1)
    if not parts:
        return {"op": "unknown", "ok": False, "error": "empty request"}

    verb = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if verb == "remember":
        if ":" in rest:
            k, _, v = rest.partition(":")
            return _op_remember(storage_dir, k.strip(), v.strip())
        return _op_remember(storage_dir, None, rest.strip())

    if verb == "recall":
        return _op_recall(storage_dir, rest.strip() or None)

    if verb in ("forget", "delete", "clear"):
        return _op_forget(storage_dir, rest.strip() or "all")

    if verb == "list":
        return _op_recall(storage_dir, None)

    return {"op": verb, "ok": False, "error": f"unknown verb: {verb!r}. Use: remember, recall, forget, list"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-memory",
        description="MARS cross-session memory MCP service agent",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Directory for memory.json (default: ~/.mars/)",
    )
    args = parser.parse_args(argv)
    storage_dir = Path(args.storage_dir) if args.storage_dir else _DEFAULT_STORAGE_DIR

    server = MCPServer("svc.memory", "1.0.0")

    @server.tool(
        "memory",
        "Cross-session key-value memory. "
        "Use 'remember key: value' to store, 'recall key' to retrieve, "
        "'recall' (no key) to list all, 'forget key' to delete, 'forget all' to clear. "
        "Also accepts JSON: {'op': 'remember', 'key': '...', 'value': '...'}.",
    )
    def memory(request: str) -> dict:
        return _dispatch(storage_dir, request)

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
