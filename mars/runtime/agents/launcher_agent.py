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
import json
import sys

from mars.runtime.services.mcp_server import MCPServer

_VALID_PROVIDERS = frozenset(
    {"anthropic", "copilot", "github-models", "ollama", "mock"}
)


def _parse_spawn_request(text: str) -> tuple[str, str]:
    """Return (provider, model) from a plain-text or JSON request.

    Supports:
    - JSON object: ``{"provider": "anthropic", "model": "claude-opus-4-7"}``
    - Positional:  ``"anthropic"`` or ``"anthropic claude-opus-4-7"``
    """
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("provider") or ""), str(data.get("model") or "")
    except Exception:  # noqa: BLE001
        pass
    parts = text.split(None, 1)
    provider = parts[0].lower() if parts else ""
    model = parts[1] if len(parts) > 1 else ""
    return provider, model


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-launcher",
        description="MARS launcher MCP service agent",
    )
    parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    import asyncio

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
                        "'anthropic claude-opus-4-7'. "
                        "Also accepts JSON: {\"provider\": \"anthropic\", \"model\": \"…\"}"
                    ),
                }
            },
            "required": ["request"],
        },
    )
    def spawn_agent(request: str = "") -> str:
        provider, model = _parse_spawn_request(request)
        if not provider:
            return (
                f"Error: provider required. "
                f"Available: {', '.join(sorted(_VALID_PROVIDERS))}."
            )
        suffix = f" (model: {model})" if model else ""
        reply = f"Spawning '{provider}'{suffix} — agent will appear shortly."
        args: dict[str, str] = {"provider": provider}
        if model:
            args["model"] = model
        return json.dumps({"_mars_cmd": {"cmd": "spawn", "args": args}, "reply": reply})

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
