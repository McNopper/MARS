"""BuiltinAdapter — routes server-side messages to a Python BuiltinService.

Provides the same ``call`` / ``call_structured`` / ``tools`` / ``skills``
interface as ``MCPAdapter`` so the routing layer in ``MARSServer._route_message``
can treat builtin services exactly like MCP stdio services.
"""
from __future__ import annotations

import json
from typing import Any

from mars.server.services.base import BuiltinService
from mars.server.services.mcp.adapter import MCPToolInfo


class BuiltinAdapter:
    """Wraps a BuiltinService for the server's bilateral message routing layer."""

    def __init__(self, agent_id: str, service: BuiltinService) -> None:
        self.agent_id = agent_id
        self._service = service

    # ------------------------------------------------------------------
    # Interface expected by _route_message (same as MCPAdapter)
    # ------------------------------------------------------------------

    @property
    def skills(self) -> list[str]:
        return [cap.name for cap in self._service.capabilities]

    @property
    def tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(
                name=cap.name,
                description=cap.description,
                input_schema=cap.input_schema or {},
            )
            for cap in self._service.capabilities
        ]

    async def call_structured(self, tool_name: str | None, args: dict[str, Any]) -> str:
        """Call a named tool with structured kwargs; return JSON-serialised result."""
        tn = tool_name or (self.skills[0] if self.skills else "")
        try:
            result = await self._service.call_tool(tn, **args)
        except Exception as exc:
            result = {"error": str(exc)}
        return result if isinstance(result, str) else json.dumps(result, default=str)

    async def call(self, text: str, *, tool_name: str | None = None) -> str:
        """Free-form text call; delegates to call_structured with a ``request`` arg."""
        return await self.call_structured(tool_name, {"request": text})
