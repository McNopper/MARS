"""The MARS world MCP server — the single door into the world.

Every actor (your interface agent, the DM, specialists) enters through this one
MCP server. The verbs are the entire surface: look / listen / say / go / examine /
take / drop / inventory / create / destroy / rooms. Rooms are admin-authored
contexts (the map); citizens live inside them. There is no parser and no second
door; natural language becomes tool calls inside the connecting agent, never here.

Concurrency model: ``WorldSession`` owns a single worker thread that drains a
command queue (tick ≈ 100 ms) and, on a slower tick (≈ 1000 ms), prunes expired
talk. Every verb enqueues its operation and awaits the result, so all world access
— including the prune — happens on that one thread and can never race. Talk lines
carry a timestamp; lines older than the talk TTL are pruned (0 disables pruning).
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mars.world.world import World

mcp = FastMCP("mars-world")

_TICK = 0.1        # queue drain cadence (100 ms)
_PRUNE_TICK = 1.0  # prune cadence (1000 ms)


class WorldSession:
    def __init__(
        self,
        world: World,
        *,
        talk_ttl: float = 60.0,
        tick: float = _TICK,
        prune_tick: float = _PRUNE_TICK,
    ) -> None:
        self.world = world
        self.talk_ttl = talk_ttl
        self.presence: dict[str, str] = {}
        self._tick = tick
        self._prune_tick = prune_tick
        self._q: queue.Queue[tuple[callable, Future]] = queue.Queue()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="mars-world-worker", daemon=True)
        self._thread.start()

    def _submit(self, fn: callable) -> object:
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result()

    def _drain(self) -> None:
        while True:
            try:
                fn, fut = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(fn())
            except BaseException as exc:  # noqa: BLE001 — surface every error to the caller
                fut.set_exception(exc)

    def _run(self) -> None:
        last_prune = time.monotonic()
        while self._running:
            # Low-latency wait for the next command (≤ tick), then drain the rest.
            try:
                fn, fut = self._q.get(timeout=self._tick)
                try:
                    fut.set_result(fn())
                except BaseException as exc:  # noqa: BLE001
                    fut.set_exception(exc)
                self._drain()
            except queue.Empty:
                pass
            now = time.monotonic()
            if self.talk_ttl and self.talk_ttl > 0 and now - last_prune >= self._prune_tick:
                self.world.prune_all(self.talk_ttl)
                last_prune = now

    def shutdown(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)

    # --- presence helpers (run on the worker thread, so no lock needed) ---
    def _room_of(self, avatar: str) -> str:
        return self.presence.setdefault(avatar, "lobby")

    def _present_in(self, room: str) -> list[str]:
        return [a for a, r in self.presence.items() if r == room]

    # --- verbs (each runs atomically on the worker thread) ---
    def look(self, avatar: str, room: str | None = None) -> str:
        def op() -> str:
            target = room or self._room_of(avatar)
            return self.world.look(target, present=self._present_in(target))
        return self._submit(op)

    def listen(self, avatar: str, lines: int = 20) -> str:
        def op() -> str:
            ttl = self.talk_ttl if self.talk_ttl and self.talk_ttl > 0 else None
            return self.world.listen(self._room_of(avatar), lines=lines, ttl_seconds=ttl)
        return self._submit(op)

    def say(self, avatar: str, text: str) -> str:
        def op() -> str:
            return self.world.say(self._room_of(avatar), avatar, text)
        return self._submit(op)

    def go(self, avatar: str, room: str) -> str:
        def op() -> str:
            if not self.world.room_exists(room):
                return f"There is no room called '{room}'. Rooms: {', '.join(self.world.list_rooms())}"
            self.presence[avatar] = room
            return self.world.look(room, present=self._present_in(room))
        return self._submit(op)

    def take(self, avatar: str, item: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            try:
                self.world.take(room, avatar, item)
            except FileNotFoundError:
                if self.world.is_fixed(room, item):
                    return f"{item!r} is fixed here — you can't take it."
                return f"There is no '{item}' here."
            except (ValueError, FileExistsError) as exc:
                return f"Could not take {item!r}: {exc}"
            return f"Taken: {item}."
        return self._submit(op)

    def drop(self, avatar: str, item: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            try:
                self.world.drop(avatar, room, item)
            except (FileNotFoundError, ValueError, FileExistsError) as exc:
                return f"Could not drop {item!r}: {exc}"
            return f"Dropped: {item}."
        return self._submit(op)

    def inventory(self, avatar: str) -> str:
        def op() -> str:
            items = self.world.inventory(avatar)
            return "You carry: " + (", ".join(items) if items else "nothing")
        return self._submit(op)

    def examine(self, avatar: str, item: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            try:
                return self.world.read_item(room, item)
            except FileNotFoundError:
                try:
                    return self.world.read_carried(avatar, item)
                except FileNotFoundError:
                    return f"There is no '{item}' here or in your inventory."
        return self._submit(op)

    def create(self, avatar: str, name: str, content: str, kind: str = "item") -> str:
        def op() -> str:
            if kind == "room":
                parts = content.strip().split("\n", 1)
                title = parts[0] or name
                desc = parts[1].strip() if len(parts) > 1 else ""
                try:
                    self.world.create_room(name, title, desc)
                except (FileExistsError, ValueError) as exc:
                    return f"Could not build room {name!r}: {exc}"
                return f"Built room: {name} — {title}."
            room = self._room_of(avatar)
            try:
                self.world.create_item(room, name, content, kind=kind)
            except FileExistsError:
                return f"'{name}' already exists here. Take it first, or choose another name."
            except ValueError as exc:
                return f"Could not create {name!r}: {exc}"
            return f"Created: {name} ({kind}) — left here in {room}."
        return self._submit(op)

    def append(self, avatar: str, item: str, text: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            try:
                self.world.append_item(room, item, text)
            except (FileNotFoundError, ValueError) as exc:
                return f"Could not append to {item!r}: {exc}"
            return f"Appended to: {item}."
        return self._submit(op)

    def destroy(self, avatar: str, item: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            for delete, where in ((self.world.delete_item, room), (self.world.delete_carried, avatar)):
                try:
                    delete(where, item)
                    return f"Destroyed: {item}."
                except FileNotFoundError:
                    continue
            return f"There is no '{item}' here or in your inventory."
        return self._submit(op)

    def rooms(self) -> str:
        return self._submit(lambda: "Rooms: " + (", ".join(self.world.list_rooms()) or "(none)"))


_SESSION: WorldSession | None = None


def _session() -> WorldSession:
    global _SESSION
    if _SESSION is None:
        world = World(os.environ.get("MARS_WORLD_DIR", "world"))
        world.init()
        ttl = float(os.environ.get("MARS_TALK_TTL", "60"))
        _SESSION = WorldSession(world, talk_ttl=ttl)
    return _SESSION


@mcp.tool()
def look(avatar: str, room: str | None = None) -> str:
    """See a room: its description, the avatars present, and the items lying here.
    If `room` is omitted, looks at the room you currently stand in."""
    return _session().look(avatar, room)


@mcp.tool()
def listen(avatar: str, lines: int = 20) -> str:
    """Read what has recently been said in the room you stand in (the transcript tail)."""
    return _session().listen(avatar, lines)


@mcp.tool()
def say(avatar: str, text: str) -> str:
    """Speak aloud in the room you stand in. Everyone present hears it; it is recorded."""
    return _session().say(avatar, text)


@mcp.tool()
def go(avatar: str, room: str) -> str:
    """Move to another room. Switches the place you stand in (and thus your context)."""
    return _session().go(avatar, room)


@mcp.tool()
def take(avatar: str, item: str) -> str:
    """Pick up an item lying in the room you stand in. It moves to your inventory."""
    return _session().take(avatar, item)


@mcp.tool()
def drop(avatar: str, item: str) -> str:
    """Drop an item from your inventory into the room you stand in."""
    return _session().drop(avatar, item)


@mcp.tool()
def inventory(avatar: str) -> str:
    """List the items you are currently carrying."""
    return _session().inventory(avatar)


@mcp.tool()
def examine(avatar: str, item: str) -> str:
    """Read the contents of an item — one lying in the room, or one you carry."""
    return _session().examine(avatar, item)


@mcp.tool()
def create(avatar: str, name: str, content: str, kind: str = "item") -> str:
    """Author something new. kind: "item" (portable, default), "fixed" (can't be taken — a sign,
    a statue), or "room" (a new room you can go to; content is "Title\\n\\nDescription")."""
    return _session().create(avatar, name, content, kind)


@mcp.tool()
def append(avatar: str, item: str, text: str) -> str:
    """Append text to an existing item in the room (a note or whiteboard that grows over time)."""
    return _session().append(avatar, item, text)


@mcp.tool()
def destroy(avatar: str, item: str) -> str:
    """Destroy an item — one lying in the room you stand in, or one you carry. Gone for good."""
    return _session().destroy(avatar, item)


@mcp.tool()
def rooms() -> str:
    """List all rooms that exist in the world."""
    return _session().rooms()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mars-world", description="the MARS world MCP server")
    parser.add_argument("--world-dir", default=os.environ.get("MARS_WORLD_DIR", "world"),
                        help="directory holding the world's text files (default: ./world)")
    parser.add_argument("--talk-ttl", default=os.environ.get("MARS_TALK_TTL", "60"), type=float,
                        help="seconds before spoken lines are pruned (default: 60; 0 disables)")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
                        help="how to expose the world (default: stdio — spawned by your agent)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for network transports")
    parser.add_argument("--port", type=int, default=7432, help="port for network transports")
    args = parser.parse_args(argv)

    global _SESSION
    world = World(args.world_dir)
    world.init()
    _SESSION = WorldSession(world, talk_ttl=args.talk_ttl)
    rooms = len(world.list_rooms())
    where = Path(args.world_dir).resolve()
    ttl_note = f"talk TTL {args.talk_ttl:.0f}s" if args.talk_ttl and args.talk_ttl > 0 else "talk TTL off"
    if args.transport == "stdio":
        print(f"🌌 MARS world ready — {rooms} room(s) at {where} ({ttl_note}, stdio)", file=sys.stderr, flush=True)
        mcp.run()
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"🌌 MARS world serving — {rooms} room(s) at {where} ({ttl_note})", file=sys.stderr, flush=True)
        print(f"   {args.transport} → http://{args.host}:{args.port}", file=sys.stderr, flush=True)
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
