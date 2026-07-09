"""Launcher MCP Server - Agent spawning and lifecycle management for MARS.

This MCP server allows LLM agents to spawn other agents on the MARS server.
It provides agent lifecycle management capabilities including spawning,
stopping, and managing agents.

Run as: python -m mars.server.services.mcp.launcher_server
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from typing import Any, Dict, Set

from mars.server.services.mcp.builtin_server import MCPBuiltinServer


_VALID_PROVIDERS: Set[str] = frozenset(
    {"anthropic", "copilot", "github-models", "ollama", "mock"}
)


class LauncherMCPServer(MCPBuiltinServer):
    """Launcher Service as MCP Server.

    Provides tools for agent lifecycle management:
    - spawn_agent: Spawn a new LLM agent
    - stop_agent: Stop a running agent
    - list_agents: List all active agents
    - get_agent_info: Get detailed information about an agent
    """

    def __init__(self):
        super().__init__("launcher", "1.0.0")
        self._running = False

    def _parse_spawn_request(self, text: str) -> Dict[str, Any]:
        """Parse a spawn request into spawn-envelope args.

        JSON keys: provider, model, name, system_prompt, kickoff, max_tokens,
        thinking, cache_prompts, allowed_skills/skills

        Positional: "anthropic" or "anthropic claude-opus-4-8"
        """
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                args: Dict[str, Any] = {}
                for key in ("provider", "model", "name", "system_prompt", "kickoff", "max_tokens"):
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
        except Exception:
            pass

        # Positional parsing
        parts = text.split(None, 1)
        args = {}
        if parts and parts[0]:
            args["provider"] = parts[0].lower()
        if len(parts) > 1:
            args["model"] = parts[1]

        return args

    def _register_handlers(self):
        """Register launcher tools."""
        self.register_tool(
            name="spawn_agent",
            description=(
                "Spawn (launch) a new LLM agent on the MARS server. "
                "Use this when the user asks to start, launch, add, or create an agent. "
                f"Available providers: {', '.join(sorted(_VALID_PROVIDERS))}."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": (
                            "Provider name, optionally followed by model name. "
                            "Examples: 'anthropic', 'ollama llama3.2', "
                            "'anthropic claude-opus-4-8'. "
                            "Also accepts JSON: {\"provider\": \"anthropic\", \"model\": \"…\"}"
                        ),
                    }
                },
                "required": ["request"],
            },
            handler=self._spawn_agent
        )

        self.register_tool(
            name="stop_agent",
            description="Stop a running agent by ID or name",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID or name to stop"
                    }
                },
                "required": ["agent_id"],
            },
            handler=self._stop_agent
        )

        self.register_tool(
            name="list_agents",
            description="List all currently active agents on the MARS server",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_type": {
                        "type": "string",
                        "description": "Filter by agent type (optional)",
                        "enum": ["llm", "service", "human", "bridge"]
                    }
                }
            },
            handler=self._list_agents
        )

        self.register_tool(
            name="get_agent_info",
            description="Get detailed information about a specific agent",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID to query"
                    }
                },
                "required": ["agent_id"],
            },
            handler=self._get_agent_info
        )

    async def initialize(self):
        """Start the Launcher Service."""
        self._running = True
        print("Launcher MCP Server initialized", file=sys.stderr)

    async def shutdown(self):
        """Stop the Launcher Service."""
        self._running = False
        print("Launcher MCP Server shutting down", file=sys.stderr)

    # Tool handlers

    async def _spawn_agent(self, arguments: Dict[str, Any]) -> str:
        """Spawn a new agent."""
        request = arguments.get("request", "")
        args = self._parse_spawn_request(request)

        provider = str(args.get("provider") or "")
        if not provider:
            return json.dumps({
                "error": "provider_required",
                "message": f"Error: provider required. Available: {', '.join(sorted(_VALID_PROVIDERS))}."
            })

        if provider not in _VALID_PROVIDERS:
            return json.dumps({
                "error": "invalid_provider",
                "message": f"Error: invalid provider '{provider}'. Available: {', '.join(sorted(_VALID_PROVIDERS))}."
            })

        model = str(args.get("model") or "")
        suffix = f" (model: {model})" if model else ""
        label = str(args.get("name") or "") or provider
        reply = f"Spawning '{label}'{suffix} — agent will appear shortly."

        return json.dumps({
            "_mars_cmd": {"cmd": "spawn", "args": args},
            "reply": reply
        })

    async def _stop_agent(self, arguments: Dict[str, Any]) -> str:
        """Stop a running agent."""
        agent_id = arguments.get("agent_id", "")

        if not agent_id:
            return json.dumps({
                "error": "agent_id_required",
                "message": "Error: agent_id is required to stop an agent"
            })

        reply = f"Stopping agent '{agent_id}' — agent will be removed shortly."

        return json.dumps({
            "_mars_cmd": {"cmd": "stop", "args": {"agent_id": agent_id}},
            "reply": reply
        })

    async def _list_agents(self, arguments: Dict[str, Any]) -> str:
        """List all active agents."""
        agent_type = arguments.get("agent_type")

        # This would query the MARS server for active agents
        # For now, return a command envelope
        return json.dumps({
            "_mars_cmd": {
                "cmd": "list_agents",
                "args": {"agent_type": agent_type} if agent_type else {}
            },
            "reply": "Querying active agents..."
        })

    async def _get_agent_info(self, arguments: Dict[str, Any]) -> str:
        """Get detailed agent information."""
        agent_id = arguments.get("agent_id", "")

        if not agent_id:
            return json.dumps({
                "error": "agent_id_required",
                "message": "Error: agent_id is required to get agent information"
            })

        # This would query the MARS server for agent details
        return json.dumps({
            "_mars_cmd": {
                "cmd": "agent_info",
                "args": {"agent_id": agent_id}
            },
            "reply": f"Querying information for agent '{agent_id}'..."
        })


def main():
    """Main entry point for the Launcher MCP Server."""
    parser = argparse.ArgumentParser(
        prog="mars-agent-launcher",
        description="MARS launcher MCP service agent",
    )
    parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    server = LauncherMCPServer()
    server.start()


if __name__ == "__main__":
    main()
