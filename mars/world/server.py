"""The MARS world MCP server — the single door into the world.

Every actor (your interface agent, the DM, specialists) enters through this one
MCP server. The verbs are the entire surface: look / listen / say / go / examine /
take / drop / inventory / create / destroy / rooms. Rooms are admin-authored
contexts (the map); citizens live inside them. There is no parser and no second
door; natural language becomes tool calls inside the connecting agent, never here.

``WorldSession`` pairs a :class:`~mars.world.world.World` with in-memory presence
(which avatar stands in which room) and is unit-testable without MCP. The FastMCP
layer below is a thin wrapper over it.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mars.world.world import World

mcp = FastMCP("mars-world")


class WorldSession:
    def __init__(self, world: World) -> None:
        self.world = world
        self.presence: dict[str, str] = {}

    def _room_of(self, avatar: str) -> str:
        return self.presence.setdefault(avatar, "lobby")

    def _present_in(self, room: str) -> list[str]:
        return [a for a, r in self.presence.items() if r == room]

    def look(self, avatar: str, room: str | None = None) -> str:
        target = room or self._room_of(avatar)
        return self.world.look(target, present=self._present_in(target))

    def listen(self, avatar: str, lines: int = 20) -> str:
        return self.world.listen(self._room_of(avatar), lines=lines)

    def say(self, avatar: str, text: str) -> str:
        return self.world.say(self._room_of(avatar), avatar, text)

    def go(self, avatar: str, room: str) -> str:
        if not self.world.room_exists(room):
            return f"There is no room called '{room}'. Rooms: {', '.join(self.world.list_rooms())}"
        self.presence[avatar] = room
        return self.world.look(room, present=self._present_in(room))

    def take(self, avatar: str, item: str) -> str:
        room = self._room_of(avatar)
        try:
            self.world.take(room, avatar, item)
        except (FileNotFoundError, ValueError) as exc:
            return f"Could not take {item!r}: {exc}"
        return f"Taken: {item}."

    def drop(self, avatar: str, item: str) -> str:
        room = self._room_of(avatar)
        try:
            self.world.drop(avatar, room, item)
        except (FileNotFoundError, ValueError) as exc:
            return f"Could not drop {item!r}: {exc}"
        return f"Dropped: {item}."

    def inventory(self, avatar: str) -> str:
        items = self.world.inventory(avatar)
        return "You carry: " + (", ".join(items) if items else "nothing")

    def examine(self, avatar: str, item: str) -> str:
        room = self._room_of(avatar)
        try:
            return self.world.read_item(room, item)
        except FileNotFoundError:
            try:
                return self.world.read_carried(avatar, item)
            except FileNotFoundError:
                return f"There is no '{item}' here or in your inventory."

    def create(self, avatar: str, item: str, content: str) -> str:
        room = self._room_of(avatar)
        if item in self.world.items_in_room(room):
            return f"'{item}' already exists here. Take it first, or choose another name."
        self.world.put_item_in_room(room, item, content)
        return f"Created: {item} — left here in {room}."

    def destroy(self, avatar: str, item: str) -> str:
        room = self._room_of(avatar)
        for delete, where in ((self.world.delete_item, room), (self.world.delete_carried, avatar)):
            try:
                delete(where, item)
                return f"Destroyed: {item}."
            except FileNotFoundError:
                continue
        return f"There is no '{item}' here or in your inventory."

    def rooms(self) -> str:
        return "Rooms: " + (", ".join(self.world.list_rooms()) or "(none)")


_SESSION: WorldSession | None = None


def _session() -> WorldSession:
    global _SESSION
    if _SESSION is None:
        world = World(os.environ.get("MARS_WORLD_DIR", "world"))
        world.init()
        _SESSION = WorldSession(world)
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
def create(avatar: str, item: str, content: str) -> str:
    """Author a new item with the given text content and leave it in the room you stand in.
    Use this to deposit knowledge into the world — a summary, notes, a paper card."""
    return _session().create(avatar, item, content)


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
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
                        help="how to expose the world (default: stdio — spawned by your agent)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for network transports")
    parser.add_argument("--port", type=int, default=7432, help="port for network transports")
    args = parser.parse_args(argv)

    global _SESSION
    world = World(args.world_dir)
    world.init()
    _SESSION = WorldSession(world)
    rooms = len(world.list_rooms())
    where = Path(args.world_dir).resolve()
    if args.transport == "stdio":
        print(f"🌌 MARS world ready — {rooms} room(s) at {where} (stdio)", file=sys.stderr, flush=True)
        mcp.run()
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        print(f"🌌 MARS world serving — {rooms} room(s) at {where}", file=sys.stderr, flush=True)
        print(f"   {args.transport} → http://{args.host}:{args.port}", file=sys.stderr, flush=True)
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
