"""Builtin Services - built-in utility services."""

from mars.server.services.builtin.discovery import DiscoveryService

# Note: Other builtin services (status, launcher, profiler, cli) are currently
# standalone agents that haven't been converted to the unified Service interface.
# They will be migrated incrementally.

__all__ = [
    "DiscoveryService",
]
