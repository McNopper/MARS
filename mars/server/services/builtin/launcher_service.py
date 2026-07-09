"""Launcher Service — agent spawning via the MARS service interface.

Exposes ``spawn_agent`` / ``launch_agent`` capabilities so LLMs can start new
agents through the standard discovery + call-tool flow.  Also provides
``_parse_spawn_request`` for parsing freeform spawn text (JSON or positional).
"""
from __future__ import annotations

import json
from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


def _parse_spawn_request(text: str) -> dict[str, Any]:
    """Parse a spawn request (JSON object or positional) into spawn-envelope args.

    JSON keys: ``provider``, ``model``, ``name``, ``system_prompt``, ``kickoff``,
    ``max_tokens``, plus ``allowed_skills`` (or ``skills``) for role isolation.
    Positional: ``"ollama"`` or ``"ollama qwen3:4b"``.
    """
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            args: dict[str, Any] = {}
            for key in ("provider", "model", "name", "system_prompt", "kickoff",
                        "max_tokens"):
                val = data.get(key)
                if val not in (None, ""):
                    args[key] = val
            if "thinking" in data:
                args["thinking"] = bool(data["thinking"])
            if "cache_prompts" in data:
                args["cache_prompts"] = bool(data["cache_prompts"])
            skills = data.get("allowed_skills") or data.get("skills")
            if skills:
                args["allowed_skills"] = skills
            if "provider" in args:
                args["provider"] = str(args["provider"]).lower()
            return args
    except Exception:  # noqa: BLE001
        pass
    parts = text.split(None, 1)
    args = {}
    if parts and parts[0]:
        args["provider"] = parts[0].lower()
    if len(parts) > 1:
        args["model"] = parts[1]
    return args


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
                            "description": "Name of the service to use (e.g., 'ollama', 'copilot')"
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
        """Spawn a new agent. Not yet implemented — use the /spawn CLI command."""
        return {
            "error": "not_implemented",
            "message": "LauncherService.spawn_agent is not yet wired to the server spawn path. Use /spawn from the CLI."
        }

    async def _launch_agent(self, service: str, model: str | None = None, kickoff: str | None = None) -> dict[str, Any]:
        """Launch an agent. Not yet implemented — use the /spawn CLI command."""
        return {
            "error": "not_implemented",
            "message": "LauncherService.launch_agent is not yet wired to the server spawn path. Use /spawn from the CLI."
        }