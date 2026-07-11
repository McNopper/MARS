"""World engine — durable state as text files under a root directory.

Layout::

    root/
      rooms/<room>.md          a room (= a context): description + transcript
      artifacts/<room>/<item>  items lying in a room
      avatars/<avatar>/<item>  an avatar's inventory

A room is an abstract boundary — a place, a sea, a chest, or an abstract context
like a task. The map is just the outermost room. A room file is a Markdown title,
a description, a ``---`` line, then the running transcript. Each transcript line is
``<iso8601>\\t<avatar>: <text>`` so old talk can be pruned by age; the timestamp is
stripped for display.

All file access is serialized by a single reentrant lock. At runtime the MCP server
routes every verb through one worker thread (see ``WorldSession``), so the lock is
uncontended and the worker also owns the prune tick — they can never race.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

_SEPARATOR = "---"

_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")
_ITEM_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-\. ]*$")


def _validate(name: str, label: str, pattern: re.Pattern[str]) -> str:
    if not name or not pattern.match(name) or name in (".", ".."):
        raise ValueError(f"invalid {label}: {name!r}")
    return name


class World:
    def __init__(self, root: Path | str = "world") -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    def init(self, *, lobby: bool = True) -> None:
        with self._lock:
            for d in ("rooms", "artifacts", "avatars"):
                (self.root / d).mkdir(parents=True, exist_ok=True)
            if lobby:
                if not self.room_exists("lobby"):
                    self.create_room(
                        "lobby",
                        "The Lobby",
                        "A bright, open room. The MARS world starts here.",
                    )
                if not self.room_exists("library"):
                    self.create_room(
                        "library",
                        "The Library",
                        "Dusty shelves line the walls, stuffed with notes and references "
                        "left by earlier travellers. A quiet place to read and think.",
                    )

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
            path = self.room_path(room)
            if path.is_file() and not exist_ok:
                raise FileExistsError(f"room {room!r} already exists; pass exist_ok=True to overwrite")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# {title}\n\n{description.strip()}\n\n{_SEPARATOR}\n",
                encoding="utf-8",
            )
            (self.root / "artifacts" / room).mkdir(parents=True, exist_ok=True)

    def _read_room(self, room: str) -> tuple[str, str]:
        text = self.room_path(room).read_text(encoding="utf-8")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip() == _SEPARATOR:
                return "\n".join(lines[:i]).strip(), "\n".join(lines[i + 1 :]).strip()
        return text.strip(), ""

    def _write_room(self, room: str, description: str, transcript: str) -> None:
        out = description.rstrip() + "\n\n" + _SEPARATOR + "\n"
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
            description, _ = self._read_room(room)
            parts = [description]
            folks = sorted(present or [])
            if folks:
                parts.append("Present: " + ", ".join(folks))
            items = self.items_in_room(room)
            if items:
                parts.append("Items: " + ", ".join(items))
            return "\n".join(parts)

    def listen(self, room: str, lines: int = 20, ttl_seconds: float | None = None) -> str:
        with self._lock:
            if not self.room_exists(room):
                return f"There is no room called '{room}'."
            _, transcript = self._read_room(room)
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
            with self.room_path(room).open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{spoken}\n")
            return spoken

    def prune_room(self, room: str, ttl_seconds: float) -> int:
        """Remove transcript lines older than ttl_seconds. Lines without a timestamp are kept."""
        with self._lock:
            if not self.room_exists(room):
                return 0
            description, transcript = self._read_room(room)
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
                self._write_room(room, description, "\n".join(kept))
            return removed

    def prune_all(self, ttl_seconds: float) -> int:
        with self._lock:
            return sum(self.prune_room(r, ttl_seconds) for r in self.list_rooms())

    def _artifacts_dir(self, room: str) -> Path:
        return self.root / "artifacts" / room

    def _fixed_dir(self, room: str) -> Path:
        return self._artifacts_dir(room) / "fixed"

    def _inventory_dir(self, avatar: str) -> Path:
        return self.root / "avatars" / avatar

    def items_in_room(self, room: str) -> list[str]:
        with self._lock:
            names: set[str] = set()
            d = self._artifacts_dir(room)
            if d.is_dir():
                names.update(p.name for p in d.glob("*") if p.is_file())
            fd = self._fixed_dir(room)
            if fd.is_dir():
                names.update(p.name for p in fd.glob("*") if p.is_file())
            return sorted(names)

    def is_fixed(self, room: str, item: str) -> bool:
        with self._lock:
            return (self._fixed_dir(room) / item).is_file()

    def inventory(self, avatar: str) -> list[str]:
        with self._lock:
            d = self._inventory_dir(avatar)
            return sorted(p.name for p in d.glob("*") if p.is_file()) if d.is_dir() else []

    def read_item(self, room: str, item: str) -> str:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            for d in (self._artifacts_dir(room), self._fixed_dir(room)):
                path = d / item
                if path.is_file():
                    return path.read_text(encoding="utf-8")
            raise FileNotFoundError(f"no item '{item}' in room '{room}'")

    def read_carried(self, avatar: str, item: str) -> str:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            path = self._inventory_dir(avatar) / item
            if not path.is_file():
                raise FileNotFoundError(f"you are not carrying '{item}'")
            return path.read_text(encoding="utf-8")

    def delete_item(self, room: str, item: str) -> None:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            for d in (self._artifacts_dir(room), self._fixed_dir(room)):
                path = d / item
                if path.is_file():
                    path.unlink()
                    return
            raise FileNotFoundError(f"no item '{item}' in room '{room}'")

    def delete_carried(self, avatar: str, item: str) -> None:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            path = self._inventory_dir(avatar) / item
            if not path.is_file():
                raise FileNotFoundError(f"you are not carrying '{item}'")
            path.unlink()

    def take(self, room: str, avatar: str, item: str) -> Path:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            src = self._artifacts_dir(room) / item
            if not src.is_file():
                raise FileNotFoundError(f"no item '{item}' in room '{room}'")
            dst_dir = self._inventory_dir(avatar)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / item
            if dst.exists():
                raise FileExistsError(f"{avatar!r} already carries {item!r}")
            src.replace(dst)
            return dst

    def drop(self, avatar: str, room: str, item: str) -> Path:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            src = self._inventory_dir(avatar) / item
            if not src.is_file():
                raise FileNotFoundError(f"you are not carrying '{item}'")
            dst_dir = self._artifacts_dir(room)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / item
            if dst.exists():
                raise FileExistsError(f"{item!r} is already lying in room '{room}'")
            src.replace(dst)
            return dst

    def put_item_in_room(self, room: str, item: str, content: str) -> Path:
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            dst_dir = self._artifacts_dir(room)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / item
            dst.write_text(content, encoding="utf-8")
            return dst

    def create_item(self, room: str, item: str, content: str, *, kind: str = "item") -> Path:
        """Atomically create a new item; raise FileExistsError if it already exists.
        kind is "item" (portable, default) or "fixed" (cannot be taken)."""
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            dst_dir = self._fixed_dir(room) if kind == "fixed" else self._artifacts_dir(room)
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / item
            with dst.open("x", encoding="utf-8") as fh:
                fh.write(content)
            return dst

    def modify_item(self, room: str, item: str, text: str) -> Path:
        """Append text to an existing in-room item (portable or fixed)."""
        with self._lock:
            _validate(item, "item", _ITEM_RE)
            for d in (self._artifacts_dir(room), self._fixed_dir(room)):
                path = d / item
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    path.write_text(content + "\n" + text.strip(), encoding="utf-8")
                    return path
            raise FileNotFoundError(f"no item '{item}' in room '{room}'")
