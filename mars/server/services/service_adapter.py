"""Generic adapter for routing bilateral calls to a Service instance."""
from __future__ import annotations

import json
from typing import Any

from mars.server.services.base import Service
from mars.server.services.mcp.adapter import MCPToolInfo


class ServiceAdapter:
    """Wrap a ``Service`` so the server can route messages to it like an agent."""

    def __init__(self, agent_id: str, service: Service) -> None:
        self.agent_id = agent_id
        self._service = service

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

    def _first_tool_accepts_request(self) -> bool:
        if not self._service.capabilities:
            return False
        schema = self._service.capabilities[0].input_schema or {}
        props = schema.get("properties") or {}
        return "request" in props or not props

    async def call_structured(self, tool_name: str | None, args: dict[str, Any]) -> str:
        tn = tool_name or (self.skills[0] if self.skills else "")
        result = await self._service.call_tool(tn, **args)
        return result if isinstance(result, str) else json.dumps(result, default=str)

    async def call(self, text: str, *, tool_name: str | None = None) -> str:
        if tool_name is None and self._first_tool_accepts_request():
            return await self.call_structured(tool_name, {"request": text})
        return await self.call_structured(tool_name, {})
