"""World engine — durable state as text files under a root directory.

Layout::

    root/
      rooms/<room>.md          a room (= a context): description + protocol + transcript

A room is an abstract boundary — a place, a sea, a chest, or an abstract context
like a task. The map is just the outermost room. A room file has three sections,
separated by lines containing only ``---``:

1. a Markdown title plus the **fixed description** (set at creation; no verb
   can change it),
2. the **protocol** — a durable document everyone in the room works on: a
   contract, a backlog, minutes. It is the common, *reduced* output of the
   conversation, distilled by the participants (never by the server),
3. the running **transcript** of what has been said — volatile. Each line is
   ``<iso8601>\t<avatar>: <text>`` so old talk can be pruned by age; the
   timestamp is stripped for display.

A file with a single ``---`` separator is the legacy two-section format
(description + transcript); its protocol reads as empty until someone writes one.

All file access is serialized by a single reentrant lock. At runtime the MCP server
routes every verb through one worker thread (see ``WorldSession``), so the lock is
uncontended and the worker also owns the prune tick — they can never race.

Note on clocks: transcript timestamps are *wall-clock* (``datetime.now()``) on
purpose — they are persisted in the room file and stay meaningful across
restarts. Presence TTLs in ``server.py`` use a *monotonic* clock instead,
because they are pure in-memory intervals that must be immune to clock jumps.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

_SEPARATOR = "---"

_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")

MAX_READ_CHARS = 64_000  # protocol reads are capped at this many characters (truncated with a note)

# Fallback used only when no LOBBY.md sits next to the world dir. The canonical lobby
# text lives in LOBBY.md at the repo root — edit that file to change what newcomers see.
DEFAULT_LOBBY_TITLE = "The Lobby"
DEFAULT_LOBBY_DESCRIPTION = (
    "MARS is a chat server where humans and AI agents meet as avatars in text rooms "
    "and coordinate by talking. This is the entry room — other rooms branch off from here. "
    "Look around, listen, then go."
)


def _validate(name: str, label: str, pattern: re.Pattern[str]) -> str:
    if not name or not pattern.match(name) or name in (".", ".."):
        raise ValueError(f"invalid {label}: {name!r}")
    return name


def _check_no_separator(text: str, label: str) -> None:
    """Lines of exactly ``---`` are reserved as section separators."""
    for line in text.splitlines():
        if line.strip() == _SEPARATOR:
            raise ValueError(f"{label} must not contain a line of exactly '{_SEPARATOR}' (reserved separator)")


class World:
    def __init__(self, root: Path | str = "world", *, lobby_path: Path | str | None = None) -> None:
        self.root = Path(root)
        # LOBBY.md is sought next to the world dir by default — so a checkout run from
        # the repo root finds ./LOBBY.md, and MARS_WORLD_DIR=/data/world finds /data/LOBBY.md.
        self.lobby_path = Path(lobby_path) if lobby_path is not None else self.root.parent / "LOBBY.md"
        self._lock = threading.RLock()

    def init(self, *, lobby: bool = True) -> None:
        with self._lock:
            (self.root / "rooms").mkdir(parents=True, exist_ok=True)
            if lobby and not self.room_exists("lobby"):
                title, description = self._lobby_seed()
                self.create_room("lobby", title, description)

    def _lobby_seed(self) -> tuple[str, str]:
        """Return ``(title, description)`` for seeding the lobby.

        Reads ``self.lobby_path`` if it exists (first non-empty line is the title,
        optionally a ``#`` markdown heading; the rest is the description), otherwise
        falls back to the built-in default. Mirrors the ``create_room`` content
        convention (``"Title\\n\\nDescription"``)."""
        path = self.lobby_path
        with self._lock:
            if not path.is_file():
                return DEFAULT_LOBBY_TITLE, DEFAULT_LOBBY_DESCRIPTION
            content = path.read_text(encoding="utf-8").strip()
            parts = content.split("\n", 1)
            title = parts[0].strip().lstrip("#").strip() or DEFAULT_LOBBY_TITLE
            description = parts[1].strip() if len(parts) > 1 else ""
            return title, description

    def room_path(self, room: str) -> Path:
        _validate(room, "room", _NAME_RE)
        return self.root / "rooms" / f"{room}.md"

    def room_exists(self, room: str) -> bool:
        with self._lock:
            return self.room_path(room).is_file()

    def list_rooms(self) -> list[str]:
        with self._lock:
            rooms_dir = self.root / "rooms"
            return sorted(p.stem for p in rooms_dir.glob("*.md")) if rooms_dir.is_dir() else []

    def create_room(self, room: str, title: str, description: str, *, exist_ok: bool = False) -> None:
        with self._lock:
            _validate(room, "room", _NAME_RE)
            if not title.strip():
                raise ValueError("room title must not be empty")
            description = description.strip() or title.strip()
            _check_no_separator(description, "room description")
            path = self.room_path(room)
            if path.is_file() and not exist_ok:
                raise FileExistsError(f"room {room!r} already exists; pass exist_ok=True to overwrite")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_room(room, f"# {title.strip()}\n\n{description}", "", "")

    def _read_room(self, room: str) -> tuple[str, str, str]:
        """Return (description, protocol, transcript). A single ``---`` separator means
        the legacy two-section format: description + transcript, protocol empty."""
        text = self.room_path(room).read_text(encoding="utf-8")
        lines = text.split("\n")
        seps = [i for i, line in enumerate(lines) if line.strip() == _SEPARATOR]
        if not seps:
            return text.strip(), "", ""
        description = "\n".join(lines[: seps[0]]).strip()
        if len(seps) == 1:
            return description, "", "\n".join(lines[seps[0] + 1 :]).strip()
        protocol = "\n".join(lines[seps[0] + 1 : seps[1]]).strip()
        transcript = "\n".join(lines[seps[1] + 1 :]).strip()
        return description, protocol, transcript

    def _write_room(self, room: str, description: str, protocol: str, transcript: str) -> None:
        out = description.rstrip() + "\n\n" + _SEPARATOR + "\n"
        if protocol.strip():
            out += "\n" + protocol.strip() + "\n\n"
        out += _SEPARATOR + "\n"
        if transcript.strip():
            out += transcript.strip() + "\n"
        self.room_path(room).write_text(out, encoding="utf-8")

    @staticmethod
    def _parse_line(line: str) -> tuple[datetime | None, str]:
        """Split a transcript line into (timestamp, content); timestamp is None if absent/invalid."""
        head, sep, content = line.partition("\t")
        if sep:
            try:
                return datetime.fromisoformat(head), content
            except ValueError:
                pass
        return None, line

    def look(self, room: str, present: list[str] | None = None) -> str:
        with self._lock:
            if not self.room_exists(room):
                available = ", ".join(self.list_rooms()) or "(none)"
                return f"There is no room called '{room}'. Rooms: {available}"
            description, protocol, _ = self._read_room(room)
            parts = [description]
            folks = sorted(present or [])
            if folks:
                parts.append("Present: " + ", ".join(folks))
            lines = len(protocol.splitlines()) if protocol else 0
            if lines:
                parts.append(f"Protocol: {lines} line(s) — call read to see it")
            return "\n".join(parts)

    def listen(self, room: str, lines: int = 20, ttl_seconds: float | None = None) -> str:
        with self._lock:
            if not self.room_exists(room):
                return f"There is no room called '{room}'."
            _, _, transcript = self._read_room(room)
            if not transcript:
                return "(silence)"
            now = datetime.now()
            contents: list[str] = []
            for line in transcript.splitlines():
                ts, content = self._parse_line(line)
                if ttl_seconds is not None and ts is not None and (now - ts).total_seconds() > ttl_seconds:
                    continue
                contents.append(content)
            if not contents:
                return "(silence)"
            return "\n".join(contents[-lines:])

    def say(self, room: str, avatar: str, text: str) -> str:
        with self._lock:
            if not self.room_exists(room):
                raise FileNotFoundError(f"no room called {room!r}")
            spoken = f"{avatar}: {text.strip()}"
            # Append-only fast path: the transcript is always the last section.
            with self.room_path(room).open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{spoken}\n")
            return spoken

    def prune_room(self, room: str, ttl_seconds: float) -> int:
        """Remove transcript lines older than ttl_seconds. Lines without a timestamp are kept."""
        with self._lock:
            if not self.room_exists(room):
                return 0
            description, protocol, transcript = self._read_room(room)
            now = datetime.now()
            kept: list[str] = []
            removed = 0
            for line in transcript.splitlines():
                ts, _ = self._parse_line(line)
                if ts is not None and (now - ts).total_seconds() > ttl_seconds:
                    removed += 1
                else:
                    kept.append(line)
            if removed:
                self._write_room(room, description, protocol, "\n".join(kept))
            return removed

    def prune_all(self, ttl_seconds: float) -> int:
        with self._lock:
            return sum(self.prune_room(r, ttl_seconds) for r in self.list_rooms())

    # --- the protocol: the room's durable, shared document ---

    def read_protocol(self, room: str) -> str:
        with self._lock:
            if not self.room_exists(room):
                raise FileNotFoundError(f"no room called {room!r}")
            _, protocol, _ = self._read_room(room)
            if not protocol:
                return "(no protocol yet — write one)"
            if len(protocol) > MAX_READ_CHARS:
                return (
                    protocol[:MAX_READ_CHARS]
                    + f"\n\n… (truncated — {len(protocol)} chars total, showing the first {MAX_READ_CHARS})"
                )
            return protocol

    def write_protocol(self, room: str, text: str) -> None:
        """Replace the room's whole protocol document (the distilled common output).
        Last writer wins — the session serialises all writes on one worker thread."""
        with self._lock:
            if not self.room_exists(room):
                raise FileNotFoundError(f"no room called {room!r}")
            _check_no_separator(text, "protocol")
            description, _, transcript = self._read_room(room)
            self._write_room(room, description, text.strip(), transcript)

    def append_protocol(self, room: str, text: str) -> None:
        """Atomically append to the room's protocol — no read-modify-write race."""
        with self._lock:
            if not self.room_exists(room):
                raise FileNotFoundError(f"no room called {room!r}")
            _check_no_separator(text, "protocol")
            description, protocol, transcript = self._read_room(room)
            merged = (protocol + "\n\n" + text.strip()) if protocol else text.strip()
            self._write_room(room, description, merged, transcript)
