"""Launcher Service - Unified Service wrapper for the launcher MCP agent.

This provides a Service interface wrapper around the launcher MCP server agent,
allowing it to be discovered and used alongside other services in the unified
architecture.
"""
from __future__ import annotations

from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


class LauncherService(BuiltinService):
    """Launcher Service wrapper - provides agent spawning capabilities.

    This service wraps the launcher MCP server agent to provide a unified
    Service interface while maintaining the existing MCP functionality.
    """

    def __init__(self) -> None:
        self._service_id = "launcher"
        self._running = False
        # The actual launcher agent runs as an MCP server
        self._agent_process = None

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return "Launcher Service"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Expose launcher capabilities as tools."""
        return [
            ServiceCapability(
                name="spawn_agent",
                description="Spawn a new agent with specified service and model",
                input_schema={
                    "type": "object",
                    "properties": {
                        "service_name": {
                            "type": "string",
                            "description": "Name of the service to use (e.g., 'anthropic', 'ollama')"
                        },
                        "model": {
                            "type": "string",
                            "description": "Model identifier (optional)"
                        },
                        "agent_name": {
                            "type": "string",
                            "description": "Name for the new agent"
                        }
                    },
                    "required": ["service_name"]
                }
            ),
            ServiceCapability(
                name="launch_agent",
                description="Launch an agent with the given configuration",
                input_schema={
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Service to use"
                        },
                        "model": {
                            "type": "string",
                            "description": "Model to use"
                        },
                        "kickoff": {
                            "type": "string",
                            "description": "Initial message/prompt for the agent"
                        }
                    },
                    "required": ["service"]
                }
            ),
        ]

    async def initialize(self) -> None:
        """Start the Launcher Service."""
        self._running = True

    async def shutdown(self) -> None:
        """Stop the Launcher Service."""
        self._running = False

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a launcher tool."""
        if tool_name == "spawn_agent":
            return await self._spawn_agent(**kwargs)
        elif tool_name == "launch_agent":
            return await self._launch_agent(**kwargs)
        else:
            return f"Unknown launcher tool: {tool_name}"

    async def _spawn_agent(self, service_name: str, model: str | None = None, agent_name: str | None = None) -> dict[str, Any]:
        """Spawn a new agent with the specified service and model."""
        # This would interface with the launcher agent logic
        # For now, return a placeholder response
        return {
            "service": service_name,
            "model": model or "default",
            "agent_name": agent_name or f"agent.{service_name}",
            "message": f"Agent {agent_name or service_name} would be spawned with {service_name} service"
        }

    async def _launch_agent(self, service: str, model: str | None = None, kickoff: str | None = None) -> dict[str, Any]:
        """Launch an agent with the given configuration."""
        return {
            "service": service,
            "model": model or "default",
            "kickoff": kickoff or "",
            "message": f"Agent would be launched with {service} service and model {model}"
        }