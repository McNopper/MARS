"""Backward-compatible re-export shim for mars.common data types.

The contents of this module were split into:
  * :mod:`mars.common.agent_record` — records, avatar/emoji tables, role/port constants
  * :mod:`mars.common.state`        — the :class:`MARSState` aggregate

Navigation helpers (_nav_*, _is_conversational, etc.) moved to :mod:`mars.cli.nav`
because they are TUI-only concerns; the server never uses them.
"""
from mars.common.agent_record import *  # noqa: F401, F403
from mars.common.state import *         # noqa: F401, F403

from mars.common.agent_record import (
    AGENT_EMOJIS,
    DEFAULT_FEDERATION_PORT,
    DEFAULT_PORT,
    EVENT_ICONS,
    HUMAN_AVATARS,
    VENDOR_EMOJIS,
    A2APeer,
    AgentRecord,
    ChatMessage,
    FeedItem,
    _AGENT_ROLE,
)
from mars.common.state import MARSState

__all__ = [
    # agent_record
    "HUMAN_AVATARS",
    "AGENT_EMOJIS",
    "VENDOR_EMOJIS",
    "EVENT_ICONS",
    "ChatMessage",
    "AgentRecord",
    "FeedItem",
    "A2APeer",
    "_AGENT_ROLE",
    "DEFAULT_PORT",
    "DEFAULT_FEDERATION_PORT",
    # state
    "MARSState",
]
