"""Status MCP Server - Runtime status and introspection for MARS.

This MCP server provides runtime status information including agents, scopes,
problems, and recent activity. It queries the MARS REST API to collect status data.

Run as: python -m mars.server.services.mcp.status_server --rest <url>
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
import sys
from datetime import UTC, datetime
from typing import Any, Dict

from mars.server.services.mcp.builtin_server import MCPBuiltinServer


class StatusMCPServer(MCPBuiltinServer):
    """Status Service as MCP Server.

    Provides tools for runtime status and introspection:
    - get_status: Return a summary of the MARS runtime
    - get_agents: Get list of active agents
    - get_scopes: Get domain scopes information
    - get_problems: Get current system problems
    """

    def __init__(self, rest_base: str = "http://localhost:7433"):
        super().__init__("status", "1.0.0")
        self.rest_base = rest_base.rstrip("/")
        self._running = False

    def _http_get_json(self, url: str, timeout: float = 5.0) -> Any:
        """Make HTTP GET request and parse JSON response."""
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
            # Translate connection errors to actionable messages
            text = str(exc).lower()
            if (
                "refused" in text
                or "10061" in text
                or "actively refused" in text
                or "verweigert" in text  # German "refused"
            ):
                return {
                    "error": "rest_unreachable",
                    "message": (
                        f"MARS REST API at {url} is not reachable (connection refused). "
                        "Is mars-server running with --http-port set?"
                    ),
                }
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _register_handlers(self):
        """Register status tools."""
        self.register_tool(
            name="get_status",
            description="Return a summary of the MARS runtime: agents, scopes, and problems",
            input_schema={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "Ignored; any value triggers the snapshot"
                    },
                }
            },
            handler=self._get_status
        )

        self.register_tool(
            name="get_agents",
            description="Get detailed list of all active agents in the system",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of agents to return (default: all)"
                    }
                }
            },
            handler=self._get_agents
        )

        self.register_tool(
            name="get_scopes",
            description="Get domain scopes and their current states",
            input_schema={},
            handler=self._get_scopes
        )

        self.register_tool(
            name="get_problems",
            description="Get current system problems and issues",
            input_schema={},
            handler=self._get_problems
        )

    async def initialize(self):
        """Start the Status Service."""
        self._running = True
        print(f"Status MCP Server initialized (REST: {self.rest_base})", file=sys.stderr)

    async def shutdown(self):
        """Stop the Status Service."""
        self._running = False
        print("Status MCP Server shutting down", file=sys.stderr)

    # Tool handlers

    def _collect_status(self) -> Dict[str, Any]:
        """Collect status from all REST endpoints."""
        agents = self._http_get_json(f"{self.rest_base}/agents")
        scopes = self._http_get_json(f"{self.rest_base}/scopes")
        problems = self._http_get_json(f"{self.rest_base}/problems")

        # If every endpoint reports rest_unreachable, surface a single error
        def _unreachable(x: Any) -> bool:
            return isinstance(x, dict) and x.get("error") == "rest_unreachable"

        if _unreachable(agents) and _unreachable(scopes) and _unreachable(problems):
            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "rest_base": self.rest_base,
                "status": "rest_unreachable",
                "message": (
                    f"The MARS REST API at {self.rest_base} is not reachable. "
                    "Start mars-server so the status agent can introspect runtime state."
                ),
            }

        summary: Dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "rest_base": self.rest_base,
            "agents": agents,
            "scopes": scopes,
            "problems": problems,
        }

        if isinstance(agents, list):
            summary["agent_count"] = len(agents)
        if isinstance(scopes, list):
            summary["scope_count"] = len(scopes)
        if isinstance(problems, list):
            summary["problem_count"] = len(problems)

        return summary

    def _format_status(self, status: Dict[str, Any]) -> str:
        """Format status as human-readable text."""
        if status.get("status") == "rest_unreachable":
            return f"⚠️  {status.get('message', 'REST API unreachable')}"

        lines = ["🔍 MARS runtime status"]
        agents = status.get("agents")
        if isinstance(agents, list):
            names = ", ".join(a.get("agent_id", str(a)) for a in agents[:10])
            lines.append(f"   Agents ({len(agents)}): {names or 'none'}")

        scopes = status.get("scopes")
        if isinstance(scopes, list):
            lines.append(f"   Scopes ({len(scopes)})")

        problems = status.get("problems")
        if isinstance(problems, list):
            lines.append(f"   Problems ({len(problems)})")

        return "\n".join(lines)

    async def _get_status(self, arguments: Dict[str, Any]) -> str:
        """Return formatted status summary."""
        status_data = self._collect_status()
        return self._format_status(status_data)

    async def _get_agents(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed agent information."""
        limit = arguments.get("limit")

        agents = self._http_get_json(f"{self.rest_base}/agents")

        if isinstance(agents, list) and limit:
            agents = agents[:limit]

        return {
            "agents": agents,
            "count": len(agents) if isinstance(agents, list) else 0
        }

    async def _get_scopes(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get domain scopes information."""
        scopes = self._http_get_json(f"{self.rest_base}/scopes")

        return {
            "scopes": scopes,
            "count": len(scopes) if isinstance(scopes, list) else 0
        }

    async def _get_problems(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get current system problems."""
        problems = self._http_get_json(f"{self.rest_base}/problems")

        return {
            "problems": problems,
            "count": len(problems) if isinstance(problems, list) else 0
        }


def main():
    """Main entry point for the Status MCP Server."""
    parser = argparse.ArgumentParser(prog="mars-agent-status")
    parser.add_argument(
        "--rest",
        default="http://localhost:7433",
        help="Base URL of the MARS REST API used to query runtime state.",
    )
    args = parser.parse_args()

    server = StatusMCPServer(rest_base=args.rest)
    server.start()


if __name__ == "__main__":
    main()
