"""The MARS world: rooms as plain text files.

The world is a directory of text files. There is no database. Each room is one file
with three sections — a fixed description, a shared durable protocol (the reduced
common output of the conversation), and a volatile transcript. ``World`` performs
only file operations; live presence (which avatar is in which room) is held in
memory by the MCP server, not here - only durable state is text.
"""
from mars.world.world import World

__all__ = ["World"]
