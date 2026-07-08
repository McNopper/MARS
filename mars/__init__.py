"""MARS – Multi-Agent Runtime System."""

__version__ = "0.1.0"

from mars.cli.main import main

# Core models (truly shared between server and CLI)
from mars.common.models import (
    HUMAN_AVATARS,
    AGENT_EMOJIS,
    EVENT_ICONS,
    AgentRecord,
    ChatMessage,
    FeedItem,
    A2APeer,
    MARSState,
)
from mars.common.constants import DEFAULT_PORT, DEFAULT_FEDERATION_PORT
from mars.common.wire import decode_frame, encode_frame, iter_frames

# Service exports (for external usage)
from mars.server.services.registry import get_service, list_services, REGISTRY

__all__ = [
    "main",
    # Core models
    "HUMAN_AVATARS",
    "AGENT_EMOJIS",
    "EVENT_ICONS",
    "AgentRecord",
    "ChatMessage",
    "FeedItem",
    "A2APeer",
    "MARSState",
    "DEFAULT_PORT",
    "DEFAULT_FEDERATION_PORT",
    "decode_frame",
    "encode_frame",
    "iter_frames",
    # Services
    "get_service",
    "list_services",
    "REGISTRY",
]
