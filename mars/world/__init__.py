"""The MARS world: rooms, artifacts, and inventories as plain text files.

The world is a directory of text files. There is no database. ``World`` performs
only file operations; live presence (which avatar is in which room) is held in
memory by the MCP server, not here — only durable state is text.
"""
from mars.world.world import World

__all__ = ["World"]
