"""Standalone status service agent for mars-server.

Exposes the runtime status protocol — agents, domain scopes, problems, and
recent activity — as a JSON artifact. Switch to it in the CLI with
``/switch svc.status@1`` and send any message to receive the latest snapshot.
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

from mars.server.services.mcp_server import MCPServer


def _http_get_json(url: str, timeout: float = 5.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        # Translate the noisy low-level "WinError 10061 / Connection refused"
        # to something an LLM (or human) can act on.
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


def collect_status(rest_base: str) -> dict[str, Any]:
    agents = _http_get_json(f"{rest_base}/agents")
    scopes = _http_get_json(f"{rest_base}/scopes")
    problems = _http_get_json(f"{rest_base}/problems")

    # If every endpoint reports rest_unreachable, surface a single top-level
    # diagnostic instead of three copies of the same error.
    def _unreachable(x: Any) -> bool:
        return isinstance(x, dict) and x.get("error") == "rest_unreachable"

    if _unreachable(agents) and _unreachable(scopes) and _unreachable(problems):
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "rest_base": rest_base,
            "status": "rest_unreachable",
            "message": (
                f"The MARS REST API at {rest_base} is not reachable. "
                "Start mars-server (or pass --rest <url> to mars-agent-status) "
                "so the status agent can introspect runtime state."
            ),
        }

    summary: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "rest_base": rest_base,
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


def _format_status(s: dict) -> str:
    if s.get("status") == "rest_unreachable":
        return f"⚠️  {s.get('message', 'REST API unreachable')}"
    lines = ["🔍 MARS runtime status"]
    agents = s.get("agents")
    if isinstance(agents, list):
        names = ", ".join(a.get("agent_id", str(a)) for a in agents[:10])
        lines.append(f"   Agents ({len(agents)}): {names or 'none'}")
    scopes = s.get("scopes")
    if isinstance(scopes, list):
        lines.append(f"   Scopes ({len(scopes)})")
    problems = s.get("problems")
    if isinstance(problems, list):
        lines.append(f"   Problems ({len(problems)})")
    return "\n".join(lines)


async def run_agent(server: str, rest_base: str) -> None:
    from mars.server.services.service_utils import build_hello, run_wire_agent
    await run_wire_agent(
        server,
        build_hello("svc.status@1", ["status", "protocol", "introspection", "runtime"]),
        lambda _: collect_status(rest_base),
        "status.json",
        in_executor=False,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mars-agent-status")
    parser.add_argument(
        "--rest",
        default="http://localhost:7433",
        help="Base URL of the MARS REST API used to query runtime state.",
    )
    args = parser.parse_args(argv)
    rest_base = args.rest.rstrip("/")

    server = MCPServer("svc.status", "1.0.0")

    @server.tool(
        "get_status",
        "Return a summary of the MARS runtime: agents, scopes, and problems.",
        {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Ignored; any value triggers the snapshot"},
            },
        },
    )
    def get_status(request: str = "") -> str:  # noqa: ARG001
        return _format_status(collect_status(rest_base))

    server.run()


if __name__ == "__main__":
    main()
