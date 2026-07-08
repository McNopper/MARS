"""CLI Service – service-registry stub for the CLI connection handler.

The actual CLI handling is performed by the TCP loop in mars.server.main.
This wrapper exists so the registry can list and discover the CLI service
like any other builtin without needing its own subprocess or MCP channel.
"""
from __future__ import annotations

from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


class CLIService(BuiltinService):
    """Builtin stub: CLI connection handler."""

    def __init__(self) -> None:
        self._service_id = "cli"
        self._running = False

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return "CLI Service"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        return []

    async def initialize(self) -> None:
        self._running = True

    async def shutdown(self) -> None:
        self._running = False

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        return f"CLI service does not expose tools (requested: {tool_name})"
