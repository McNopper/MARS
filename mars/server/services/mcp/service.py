"""MCP Service implementation wrapping the legacy MCPAdapter.

This provides a unified Service interface for MCP services.
"""
from __future__ import annotations

from typing import Any

from mars.server.services.base import Service, ServiceCapability
from mars.server.services.mcp.adapter import MCPAdapter, MCPToolInfo


class MCPService(Service):
    """Service wrapper for an MCP stdio subprocess."""

    def __init__(self, service_id: str, command: list[str]) -> None:
        self._service_id = service_id
        self._command = command
        self._adapter = MCPAdapter(service_id, command)
        self._running = False

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return self._service_id

    @property
    def service_type(self) -> str:
        return "mcp"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Expose MCP tools as ServiceCapabilities."""
        if not self._adapter.tools:
            return []
        return [
            ServiceCapability(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in self._adapter.tools
        ]

    async def initialize(self) -> None:
        """Start the MCP service."""
        if not self._running:
            await self._adapter.start()
            self._running = True

    async def shutdown(self) -> None:
        """Stop the MCP service."""
        if self._running:
            await self._adapter.stop()
            self._running = False

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute an MCP tool."""
        return await self._adapter.call_structured(tool_name, kwargs)

    @property
    def is_running(self) -> bool:
        """Check if service is currently running."""
        return self._running

    # Expose adapter properties for compatibility
    @property
    def skills(self) -> list[str]:
        return self._adapter.skills

    @property
    def tools(self) -> list[MCPToolInfo]:
        return self._adapter.tools

    @property
    def adapter(self) -> MCPAdapter:
        """Access the underlying adapter for legacy compatibility."""
        return self._adapter