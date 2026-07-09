"""Status Service - Unified Service wrapper for the status MCP agent.

This provides a Service interface wrapper around the status MCP server agent,
allowing it to be discovered and used alongside other services in the unified
architecture.
"""
from __future__ import annotations

from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


class StatusService(BuiltinService):
    """Status Service wrapper - provides runtime status and introspection capabilities.

    This service wraps the status MCP server agent to provide a unified
    Service interface while maintaining the existing MCP functionality.
    """

    def __init__(self) -> None:
        self._service_id = "status"
        self._running = False

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return "Status Service"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Expose status capabilities as tools."""
        return [
            ServiceCapability(
                name="get_status",
                description="Get the current runtime status including agents, scopes, and problems",
                input_schema={
                    "type": "object",
                    "properties": {
                        "detail_level": {
                            "type": "string",
                            "description": "Level of detail: 'summary', 'basic', or 'full'",
                            "enum": ["summary", "basic", "full"],
                            "default": "summary"
                        }
                    }
                }
            ),
            ServiceCapability(
                name="list_agents",
                description="List all agents currently running in the system",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_details": {
                            "type": "boolean",
                            "description": "Whether to include detailed agent information",
                            "default": False
                        }
                    }
                }
            ),
            ServiceCapability(
                name="list_problems",
                description="List any problems or issues detected in the system",
                input_schema={
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "description": "Filter by severity: 'error', 'warning', 'info'",
                            "enum": ["error", "warning", "info"]
                        }
                    }
                }
            ),
        ]

    async def initialize(self) -> None:
        """Start the Status Service."""
        self._running = True

    async def shutdown(self) -> None:
        """Stop the Status Service."""
        self._running = False

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a status tool."""
        if tool_name == "get_status":
            return await self._get_status(**kwargs)
        elif tool_name == "list_agents":
            return await self._list_agents(**kwargs)
        elif tool_name == "list_problems":
            return await self._list_problems(**kwargs)
        else:
            return f"Unknown status tool: {tool_name}"

    async def _get_status(self, detail_level: str = "summary") -> dict[str, Any]:
        """Get the current runtime status. Not yet wired to MARSState."""
        return {
            "error": "not_implemented",
            "message": "StatusService is not yet wired to live MARSState. Runtime introspection is pending."
        }

    async def _list_agents(self, include_details: bool = False) -> dict[str, Any]:
        """List all agents currently running. Not yet wired to MARSState."""
        return {
            "error": "not_implemented",
            "message": "StatusService is not yet wired to live MARSState. Agent listing is pending."
        }

    async def _list_problems(self, severity: str | None = None) -> dict[str, Any]:
        """List any problems or issues in the system. Not yet wired to MARSState."""
        return {
            "error": "not_implemented",
            "message": "StatusService is not yet wired to live MARSState. Problem listing is pending."
        }