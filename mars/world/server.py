"""The MARS world MCP server — the single door into the world.

Every actor (your interface agent, specialists, remote agents) enters through this one
MCP server. The verbs are the entire surface: look / listen / say / go / rooms /
create_room / read / write / append. A room is a fixed description plus a shared,
durable **protocol** document (the reduced common output of the conversation) plus a
volatile transcript. There is no parser and no second door; natural language becomes
tool calls inside the connecting agent, never here.

Concurrency model: ``WorldSession`` owns a single worker thread that drains a
command queue (tick ≈ 100 ms) and, on a slower tick (≈ 1000 ms), prunes expired
talk. Every verb enqueues its operation and awaits the result, so all world access
— including the prune — happens on that one thread and can never race. Talk lines
carry a timestamp; lines older than the talk TTL are pruned (0 disables pruning).

Note on clocks: the transcript uses wall-clock timestamps (persisted, meaningful
across restarts — see ``world.py``), while presence uses ``time.monotonic()`` here
because it is a pure in-memory interval that must survive clock jumps.
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
        presence_ttl: float = 60.0,
        tick: float = _TICK,
        prune_tick: float = _PRUNE_TICK,
    ) -> None:
        self.world = world
        self.talk_ttl = talk_ttl
        self.presence_ttl = presence_ttl
        self.presence: dict[str, str] = {}
        self.last_seen: dict[str, float] = {}
        self._tick = tick
        self._prune_tick = prune_tick
        self._q: queue.Queue[tuple[object, Future]] = queue.Queue()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="mars-world-worker", daemon=True)
        self._thread.start()

    def _submit(self, fn) -> object:
        # Fail fast if the worker thread is dead rather than hanging for the full timeout.
        if not self._thread.is_alive():
            raise RuntimeError(
                "MARS worker thread is dead — the world server is no longer processing commands"
            )
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout=30)

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
            if now - last_prune >= self._prune_tick:
                try:
                    if self.talk_ttl and self.talk_ttl > 0:
                        self.world.prune_all(self.talk_ttl)
                    self._reap_idle(now)
                except Exception:
                    pass  # never let housekeeping kill the worker
                last_prune = now

    def shutdown(self) -> None:
        self._running = False
        self._thread.join(timeout=2.0)

    def _reap_idle(self, now: float) -> None:
        """Assume an avatar is gone if it hasn't called a verb within the presence TTL.
        We can't detect disconnection — we just prune on inactivity. Always-on agents
        stay because they periodically call tools (implicit heartbeat)."""
        if self.presence_ttl and self.presence_ttl > 0:
            stale = [a for a, t in self.last_seen.items() if now - t > self.presence_ttl]
            for a in stale:
                self.presence.pop(a, None)
                self.last_seen.pop(a, None)

    # --- presence helpers (run on the worker thread, so no lock needed) ---
    def _room_of(self, avatar: str) -> str:
        self.last_seen[avatar] = time.monotonic()
        return self.presence.setdefault(avatar, "lobby")

    def _present_in(self, room: str) -> list[str]:
        return [a for a, r in self.presence.items() if r == room]

    # --- verbs (each runs atomically on the worker thread) ---
    def look(self, avatar: str, room: str | None = None) -> str:
        def op() -> str:
            self.last_seen[avatar] = time.monotonic()
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
            self.last_seen[avatar] = time.monotonic()
            if not self.world.room_exists(room):
                return f"There is no room called '{room}'. Rooms: {', '.join(self.world.list_rooms())}"
            self.presence[avatar] = room
            return self.world.look(room, present=self._present_in(room))
        return self._submit(op)

    def rooms(self) -> str:
        return self._submit(lambda: "Rooms: " + (", ".join(self.world.list_rooms()) or "(none)"))

    def create_room(self, avatar: str, name: str, content: str) -> str:
        def op() -> str:
            parts = content.strip().split("\n", 1)
            title = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
            try:
                self.world.create_room(name, title, desc)
            except (FileExistsError, ValueError) as exc:
                return f"Could not build room {name!r}: {exc}"
            return f"Built room: {name} — {title}."
        return self._submit(op)

    def read(self, avatar: str) -> str:
        def op() -> str:
            try:
                return self.world.read_protocol(self._room_of(avatar))
            except FileNotFoundError as exc:
                return f"There is no room here. ({exc})"
        return self._submit(op)

    def write(self, avatar: str, text: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            try:
                self.world.write_protocol(room, text)
            except (FileNotFoundError, ValueError) as exc:
                return f"Could not write the protocol: {exc}"
            return "Protocol written."
        return self._submit(op)

    def append(self, avatar: str, text: str) -> str:
        def op() -> str:
            room = self._room_of(avatar)
            try:
                self.world.append_protocol(room, text)
            except (FileNotFoundError, ValueError) as exc:
                return f"Could not append to the protocol: {exc}"
            return "Protocol updated."
        return self._submit(op)


_SESSION: WorldSession | None = None


def _session() -> WorldSession:
    global _SESSION
    if _SESSION is None:
        world = World(os.environ.get("MARS_WORLD_DIR", "world"))
        world.init()
        ttl = float(os.environ.get("MARS_TALK_TTL", "60"))
        pttl = float(os.environ.get("MARS_PRESENCE_TTL", "60"))
        _SESSION = WorldSession(world, talk_ttl=ttl, presence_ttl=pttl)
    return _SESSION


@mcp.tool()
def look(avatar: str, room: str | None = None) -> str:
    """See a room: its fixed description, the avatars present, and a hint at its protocol.
    If `room` is omitted, looks at the room you currently stand in."""
    return _session().look(avatar, room)


@mcp.tool()
def listen(avatar: str, lines: int = 20) -> str:
    """Read what has recently been said in the room you stand in (the volatile transcript tail)."""
    return _session().listen(avatar, lines)


@mcp.tool()
def say(avatar: str, text: str) -> str:
    """Speak aloud in the room you stand in. Everyone present hears it; it is recorded (and fades)."""
    return _session().say(avatar, text)


@mcp.tool()
def go(avatar: str, room: str) -> str:
    """Move to another room. Switches the place you stand in (and thus your context)."""
    return _session().go(avatar, room)


@mcp.tool()
def rooms() -> str:
    """List all rooms that exist in the world."""
    return _session().rooms()


@mcp.tool()
def create_room(avatar: str, name: str, content: str) -> str:
    """Build a new room you and others can go to. content is "Title\\n\\nDescription".
    The description is then fixed — the room is a durable context boundary."""
    return _session().create_room(avatar, name, content)


@mcp.tool()
def read(avatar: str) -> str:
    """Read the room's protocol — the durable document everyone here works on
    (a contract, backlog, or minutes: the common, reduced output of the conversation)."""
    return _session().read(avatar)


@mcp.tool()
def write(avatar: str, text: str) -> str:
    """Replace the room's whole protocol document. Use it to distil the conversation
    into a clean, reduced contract. Last writer wins; prefer append for simple additions."""
    return _session().write(avatar, text)


@mcp.tool()
def append(avatar: str, text: str) -> str:
    """Append to the room's protocol document. Atomic — no read-modify-write race."""
    return _session().append(avatar, text)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mars-world", description="the MARS world MCP server")
    parser.add_argument("--world-dir", default=os.environ.get("MARS_WORLD_DIR", "world"),
                        help="directory holding the world's text files (default: ./world)")
    parser.add_argument("--talk-ttl", default=os.environ.get("MARS_TALK_TTL", "60"), type=float,
                        help="seconds before spoken lines are pruned (default: 60; 0 disables)")
    parser.add_argument("--presence-ttl", default=os.environ.get("MARS_PRESENCE_TTL", "60"), type=float,
                        help="seconds before an idle avatar is removed from presence (default: 60; 0 disables)")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
                        help="how to expose the world (default: stdio — spawned by your agent)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for network transports")
    parser.add_argument("--port", type=int, default=7432, help="port for network transports")
    args = parser.parse_args(argv)

    global _SESSION
    world = World(args.world_dir)
    world.init()
    _SESSION = WorldSession(world, talk_ttl=args.talk_ttl, presence_ttl=args.presence_ttl)
    rooms = len(world.list_rooms())
    where = Path(args.world_dir).resolve()
    ttl_note = f"talk TTL {args.talk_ttl:.0f}s" if args.talk_ttl and args.talk_ttl > 0 else "talk TTL off"
    pttl_note = f"presence TTL {args.presence_ttl:.0f}s" if args.presence_ttl and args.presence_ttl > 0 else "presence TTL off"
    if args.transport == "stdio":
        print(f"🌌 MARS world ready — {rooms} room(s) at {where} ({ttl_note}, {pttl_note}, stdio)", file=sys.stderr, flush=True)
        mcp.run()
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"🌌 MARS world serving — {rooms} room(s) at {where} ({ttl_note}, {pttl_note})", file=sys.stderr, flush=True)
        print(f"   {args.transport} → http://{args.host}:{args.port}", file=sys.stderr, flush=True)
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
