"""MARS Scheduler Service Agent.

Lightweight in-process scheduler for one-shot and recurring prompts.
Stores pending schedules in ~/.mars/schedules.json.

The scheduler records schedule entries and returns IDs. Clients poll
'list' to see due schedules and send them when the time arrives.

Accepted request formats
------------------------
  after 30s run the tests
  after 5m check build status
  after 1h send summary
  every 10m ping me
  cancel sched-abc12345
  list
  JSON: {"op": "after", "delay": 30, "prompt": "run tests"}
        {"op": "every", "interval": 600, "prompt": "ping me"}
        {"op": "cancel", "id": "sched-abc12345"}

Response fields
---------------
  op         Operation performed
  id         Schedule ID (for new schedules)
  delay_s    Delay in seconds (for 'after')
  interval_s Interval in seconds (for 'every')
  prompt     The scheduled prompt
  ok         true on success
  schedules  List of all schedules (for 'list')
  error      Error description on failure
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mars.runtime.services.mcp_server import MCPServer


_DEFAULT_STORAGE_DIR = Path.home() / ".mars"
_SCHEDULES_FILENAME  = "schedules.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _short_id() -> str:
    return "sched-" + uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Time-unit parsing
# ---------------------------------------------------------------------------

_UNIT_SECS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_delay(token: str) -> float | None:
    """Parse a human delay token like '30s', '5m', '1h', '2h30m'.

    Returns total seconds as a float, or None on parse failure.
    """
    token = token.strip().lower()
    if not token:
        return None

    # Pure number → treat as seconds
    try:
        return float(token)
    except ValueError:
        pass

    # Compound form: 2h30m, 1h20m10s, …
    total = 0.0
    remaining = token
    matched_any = False
    for unit, secs in [("h", 3600), ("m", 60), ("s", 1)]:
        idx = remaining.find(unit)
        if idx > 0:
            try:
                total += float(remaining[:idx]) * secs
                remaining = remaining[idx + 1:]
                matched_any = True
            except ValueError:
                return None
    return total if matched_any else None


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _load(storage_dir: Path) -> list[dict]:
    path = storage_dir / _SCHEDULES_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _persist(storage_dir: Path, schedules: list[dict]) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / _SCHEDULES_FILENAME).write_text(
        json.dumps(schedules, indent=2, ensure_ascii=False), "utf-8"
    )


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------

def _op_after(
    storage_dir: Path,
    delay_s: float,
    prompt: str,
) -> dict[str, Any]:
    schedules = _load(storage_dir)
    now = _now_ts()
    entry = {
        "id": _short_id(),
        "type": "once",
        "delay_s": delay_s,
        "due_at": now + delay_s,
        "due_at_iso": datetime.fromtimestamp(now + delay_s, tz=timezone.utc).isoformat(timespec="seconds"),
        "prompt": prompt,
        "created_at": _now_iso(),
        "status": "pending",
    }
    schedules.append(entry)
    _persist(storage_dir, schedules)
    return {
        "op": "after",
        "id": entry["id"],
        "delay_s": delay_s,
        "prompt": prompt,
        "due_at": entry["due_at_iso"],
        "ok": True,
    }


def _op_every(
    storage_dir: Path,
    interval_s: float,
    prompt: str,
) -> dict[str, Any]:
    schedules = _load(storage_dir)
    now = _now_ts()
    entry = {
        "id": _short_id(),
        "type": "recurring",
        "interval_s": interval_s,
        "next_at": now + interval_s,
        "next_at_iso": datetime.fromtimestamp(now + interval_s, tz=timezone.utc).isoformat(timespec="seconds"),
        "prompt": prompt,
        "created_at": _now_iso(),
        "status": "pending",
    }
    schedules.append(entry)
    _persist(storage_dir, schedules)
    return {
        "op": "every",
        "id": entry["id"],
        "interval_s": interval_s,
        "prompt": prompt,
        "next_at": entry["next_at_iso"],
        "ok": True,
    }


def _op_cancel(storage_dir: Path, schedule_id: str) -> dict[str, Any]:
    schedules = _load(storage_dir)
    before = len(schedules)
    schedules = [s for s in schedules if s.get("id") != schedule_id]
    if len(schedules) == before:
        return {"op": "cancel", "id": schedule_id, "ok": False,
                "error": f"schedule {schedule_id!r} not found"}
    _persist(storage_dir, schedules)
    return {"op": "cancel", "id": schedule_id, "ok": True}


def _op_list(storage_dir: Path) -> dict[str, Any]:
    schedules = _load(storage_dir)
    now = _now_ts()
    # Mark due schedules
    result = []
    for s in schedules:
        entry = dict(s)
        due_key = "due_at" if s.get("type") == "once" else "next_at"
        entry["due"] = s.get(due_key, 0) <= now
        result.append(entry)
    return {"op": "list", "ok": True, "schedules": result, "count": len(result)}


def _dispatch(storage_dir: Path, request: str) -> dict[str, Any]:
    request = request.strip()

    if request.startswith("{"):
        try:
            obj = json.loads(request)
            op = str(obj.get("op", "")).lower()
            if op == "after":
                delay = float(obj.get("delay", 0))
                prompt = str(obj.get("prompt", ""))
                if not prompt:
                    return {"op": "after", "ok": False, "error": "missing 'prompt'"}
                return _op_after(storage_dir, delay, prompt)
            if op == "every":
                interval = float(obj.get("interval", 0))
                prompt = str(obj.get("prompt", ""))
                if not prompt:
                    return {"op": "every", "ok": False, "error": "missing 'prompt'"}
                return _op_every(storage_dir, interval, prompt)
            if op == "cancel":
                return _op_cancel(storage_dir, str(obj.get("id", "")))
            if op == "list":
                return _op_list(storage_dir)
            return {"op": op, "ok": False, "error": f"unknown op: {op!r}"}
        except (json.JSONDecodeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    parts = request.split(None, 2)
    if not parts:
        return {"ok": False, "error": "empty request"}

    verb = parts[0].lower()

    if verb == "list":
        return _op_list(storage_dir)

    if verb == "cancel":
        sid = parts[1] if len(parts) > 1 else ""
        return _op_cancel(storage_dir, sid)

    if verb in ("after", "every"):
        if len(parts) < 3:
            return {"ok": False, "error": f"Usage: {verb} <delay> <prompt>"}
        delay_token = parts[1]
        prompt = parts[2]
        delay_s = _parse_delay(delay_token)
        if delay_s is None:
            return {
                "ok": False,
                "error": (
                    f"invalid delay {delay_token!r}. "
                    "Use: 30s, 5m, 1h, 2h30m"
                ),
            }
        if verb == "after":
            return _op_after(storage_dir, delay_s, prompt)
        return _op_every(storage_dir, delay_s, prompt)

    return {
        "ok": False,
        "error": f"unknown verb: {verb!r}. Use: after, every, cancel, list",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-scheduler",
        description="MARS prompt scheduler MCP service agent",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Directory for schedules.json (default: ~/.mars/)",
    )
    args = parser.parse_args(argv)
    storage_dir = Path(args.storage_dir) if args.storage_dir else _DEFAULT_STORAGE_DIR

    server = MCPServer("svc.scheduler", "1.0.0")

    @server.tool(
        "schedule",
        "Schedule one-shot or recurring prompts. "
        "Use 'after 30s <prompt>', 'every 5m <prompt>', 'cancel <id>', 'list'. "
        "Time units: s=seconds, m=minutes, h=hours. Compound: '2h30m'. "
        "Also accepts JSON: {'op': 'after', 'delay': 30, 'prompt': '...'}.",
    )
    def schedule(request: str) -> dict:
        return _dispatch(storage_dir, request)

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
