"""Base classes for all MARS services.

A service is the unit of capability in MARS.  Every service declares what it
can do via ``capabilities`` and accepts calls via ``call_tool``.  Nothing else
is assumed — LLM providers, MCP stdio servers, A2A federation peers and
built-in utilities all implement exactly the same minimal interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ServiceCapability:
    """Describes one tool/function a service exposes."""
    name: str
    description: str
    input_schema: dict[str, Any] | None = None


class Service(ABC):
    """Minimal base for every MARS service.

    A service:
    * declares what it can do via ``capabilities`` (dynamic, can change at runtime)
    * accepts tool calls via ``call_tool``
    * has a lifecycle: ``initialize`` / ``shutdown``

    No further structure is imposed — the service type tag (``service_type``)
    is purely informational for the registry and the Discovery Service.
    """

    @property
    @abstractmethod
    def service_id(self) -> str:
        """Unique identifier (e.g. ``"discovery"``, ``"ollama"``)."""

    @property
    def service_type(self) -> str:
        """Informational category: ``"llm"``, ``"mcp"``, ``"a2a"``, ``"builtin"``."""
        return "builtin"

    @property
    def display_name(self) -> str:
        """Human-readable name (defaults to ``service_id``)."""
        return self.service_id

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Dynamic list of tools this service currently exposes.

        May change at runtime (e.g. after an MCP server loads new tools).
        Return ``[]`` if the service has no callable tools of its own.
        """
        return []

    @abstractmethod
    async def initialize(self) -> None:
        """Start / connect the service."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Stop / disconnect the service."""

    @abstractmethod
    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a capability by name.

        Parameters
        ----------
        tool_name:
            One of the names from ``capabilities``.
        **kwargs:
            Arguments matching the capability's ``input_schema``.

        Returns
        -------
        Any JSON-serialisable value, or a plain string.
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.service_id})"

    @property
    def is_running(self) -> bool:
        """True if the service is currently active.  Override in subclasses."""
        return getattr(self, "_running", False)


class BuiltinService(Service):
    """Convenience base for built-in services embedded in the server process."""

    @property
    def service_type(self) -> str:
        return "builtin"
