"""A2A Service implementation wrapping the legacy A2AAdapter.

This provides a unified Service interface for A2A services.
"""
from __future__ import annotations

from typing import Any

from mars.server.services.a2a.adapter import A2AAdapter, AgentCard
from mars.server.services.base import Service, ServiceCapability


class A2AService(Service):
    """Service wrapper for an A2A peer connection."""

    def __init__(self, service_id: str, base_url: str) -> None:
        self._service_id = service_id
        self._base_url = base_url
        self._adapter = A2AAdapter(service_id, base_url)
        self._running = False
        self._card: AgentCard | None = None

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return self._service_id

    @property
    def service_type(self) -> str:
        return "a2a"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Expose A2A skills as ServiceCapabilities."""
        if not self._card:
            return []
        return [
            ServiceCapability(
                name=skill.id,
                description=skill.description,
                input_schema=None,  # A2A skills don't have input schemas
            )
            for skill in self._card.skills
        ]

    async def initialize(self) -> None:
        """Start the A2A service."""
        if not self._running:
            self._card = await self._adapter.start()
            self._running = True

    async def shutdown(self) -> None:
        """Stop the A2A service."""
        if self._running:
            await self._adapter.stop()
            self._running = False

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute an A2A skill/tool call."""
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
    def card(self) -> AgentCard | None:
        return self._card

    @property
    def adapter(self) -> A2AAdapter:
        """Access the underlying adapter for legacy compatibility."""
        return self._adapter