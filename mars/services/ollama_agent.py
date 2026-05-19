"""MARS Ollama Service Agent — lists available and running Ollama models.

Queries the local Ollama API and returns a JSON artifact describing all
installed models and which ones are currently loaded in memory.

Usage (after the agent is running)
------------------------------------
  /switch svc.ollama@1          → select the agent
  (any message)                 → returns ollama_models.json

Response fields
---------------
  host            Ollama API base URL
  installed       List of installed models (name, size, family, parameter_size)
  running         List of models currently loaded in GPU/CPU memory
  total_installed Total count of installed models
  total_running   Total count of loaded models
"""
from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request
from typing import Any

from mars.services.mcp_server import MCPServer


_DEFAULT_HOST = "http://localhost:11434"
_TIMEOUT = 8


# ---------------------------------------------------------------------------
# Ollama API helpers
# ---------------------------------------------------------------------------

def _fetch_installed(host: str) -> list[dict[str, Any]]:
    """Return list of installed models from GET /api/tags."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        models = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append({
                "name":           m.get("name", ""),
                "size_bytes":     m.get("size", 0),
                "size_gb":        round(m.get("size", 0) / 1e9, 2),
                "family":         details.get("family", ""),
                "parameter_size": details.get("parameter_size", ""),
                "quantization":   details.get("quantization_level", ""),
            })
        return models
    except Exception as exc:
        return [{"error": str(exc)}]


def _fetch_running(host: str) -> list[dict[str, Any]]:
    """Return list of currently loaded models from GET /api/ps."""
    try:
        with urllib.request.urlopen(f"{host}/api/ps", timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
        running = []
        for m in data.get("models", []):
            running.append({
                "name":       m.get("name", ""),
                "size_bytes": m.get("size", 0),
                "size_gb":    round(m.get("size", 0) / 1e9, 2),
            })
        return running
    except Exception:
        return []


def _format_snapshot(snap: dict) -> str:
    installed = snap.get("installed") or []
    running = snap.get("running") or []
    lines = [f"🦙 Ollama models at {snap.get('host')}"]
    lines.append(f"   Installed ({len(installed)}): " + (", ".join(m.get("name", str(m)) for m in installed) or "none"))
    lines.append(f"   Running  ({len(running)}): " + (", ".join(m.get("name", str(m)) for m in running) or "none"))
    return "\n".join(lines)


def _build_snapshot(host: str) -> dict[str, Any]:
    installed = _fetch_installed(host)
    running   = _fetch_running(host)
    return {
        "host":            host,
        "installed":       installed,
        "running":         running,
        "total_installed": len(installed),
        "total_running":   len(running),
    }


# ---------------------------------------------------------------------------
# Agent wire loop
# ---------------------------------------------------------------------------

async def run_agent(server: str, ollama_host: str = _DEFAULT_HOST) -> None:
    from mars.services.service_utils import build_hello, run_wire_agent
    await run_wire_agent(
        server,
        build_hello("svc.ollama-models@1", ["models", "list-models", "ollama-models", "providers", "tags"]),
        lambda _: _build_snapshot(ollama_host),
        "ollama_models.json",
        in_executor=True,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-ollama",
        description="MARS Ollama models MCP service agent",
    )
    parser.add_argument("--ollama-host", default=_DEFAULT_HOST,
                        help="Ollama API base URL")
    args = parser.parse_args(argv)
    ollama_host = args.ollama_host

    server = MCPServer("svc.ollama-models", "1.0.0")

    @server.tool(
        "list_ollama_models",
        "List locally installed and currently running Ollama models as JSON.",
        {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Ignored; any value triggers the snapshot"},
            },
        },
    )
    def list_ollama_models(request: str = "") -> str:  # noqa: ARG001
        return _format_snapshot(_build_snapshot(ollama_host))

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
