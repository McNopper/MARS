"""Profiler Service – performance monitoring builtin.

Exposes lightweight timing/sampling capabilities as tools so other agents
(and the Discovery Service) can query runtime performance metrics.
"""
from __future__ import annotations

import time
from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


class ProfilerService(BuiltinService):
    """Builtin: performance-monitoring service."""

    def __init__(self) -> None:
        self._service_id = "profiler"
        self._running = False
        self._start_time: float | None = None

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return "Profiler Service"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        return [
            ServiceCapability(
                name="get_uptime",
                description="Return the number of seconds the MARS server has been running",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    async def initialize(self) -> None:
        self._running = True
        self._start_time = time.monotonic()

    async def shutdown(self) -> None:
        self._running = False

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        if tool_name == "get_uptime":
            uptime = time.monotonic() - self._start_time if self._start_time else 0.0
            return {"uptime_seconds": round(uptime, 2)}
        return f"Unknown profiler tool: {tool_name}"
