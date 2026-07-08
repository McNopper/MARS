"""MARS Launcher service agent — lets LLM agents spawn other agents.

This agent uses the MCP stdio protocol. It does not connect to the MARS
server via TCP. Instead, it returns a ``_mars_cmd`` envelope in its tool
response that the MCPAdapter/server inspects and executes.

Removing the ``[launcher]`` entry from ``agents.ini`` disables
agent-to-agent spawning entirely. Human operators can always use
``/spawn`` from the CLI shell regardless of this setting.

Skills: spawn_agent, launch, create_agent
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from typing import Any

from mars.server.services.mcp_server import MCPServer

_VALID_PROVIDERS = frozenset(
    {"anthropic", "copilot", "github-models", "ollama", "mock"}
)


def _parse_spawn_request(text: str) -> dict[str, Any]:
    """Parse a spawn request (JSON object or positional) into spawn-envelope args.

    JSON keys: ``provider``, ``model``, ``name``, ``system_prompt``, ``kickoff``,
    ``max_tokens`` (all providers), the Anthropic-only ``thinking`` /
    ``cache_prompts``, plus ``allowed_skills`` (or ``skills``) for role isolation.
    Positional: ``"anthropic"`` or ``"anthropic claude-opus-4-8"``.
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-launcher",
        description="MARS launcher MCP service agent",
    )
    parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


    server = MCPServer("svc.launcher", "1.0.0")

    @server.tool(
        "spawn_agent",
        (
            "Spawn (launch) a new LLM agent on the MARS server. "
            "Use this when the user asks to start, launch, add, or create an agent. "
            "Available providers: 'anthropic', 'ollama', 'github-models', 'copilot', 'mock'."
        ),
        {
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
    )
    def spawn_agent(request: str = "") -> str:
        args = _parse_spawn_request(request)
        provider = str(args.get("provider") or "")
        if not provider:
            return (
                f"Error: provider required. "
                f"Available: {', '.join(sorted(_VALID_PROVIDERS))}."
            )
        model = str(args.get("model") or "")
        suffix = f" (model: {model})" if model else ""
        label = str(args.get("name") or "") or provider
        reply = f"Spawning '{label}'{suffix} — agent will appear shortly."
        return json.dumps({"_mars_cmd": {"cmd": "spawn", "args": args}, "reply": reply})

    server.run()


if __name__ == "__main__":
    main()
