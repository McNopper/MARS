"""
MARS Protocol Adapters

This package provides protocol adapters for different communication protocols used in MARS:
- AG-UI: Human CLI to agent server communication
- A2A: Agent-to-agent communication
- MCP: Service agent/toolin communication
- MARS: MARS-MARS federation communication
"""

from .base import ProtocolAdapter, ProtocolInfo, ProtocolAdapterError

__all__ = [
    "ProtocolAdapter",
    "ProtocolInfo",
    "ProtocolAdapterError",
]
