"""Standalone profiler service agent for mars-server."""
from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any

from mars.services.mcp_server import MCPServer


if sys.platform != "win32":
    import resource
else:
    resource = None  # type: ignore[assignment]


def collect_stats() -> dict[str, Any]:
    stats: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count() or 1,
        "process_time_seconds": round(os.times().user + os.times().system, 6),
        "rss_bytes": None,
        "memory_percent": None,
        "cpu_percent": None,
        "load_average": None,
    }
    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        stats["rss_bytes"] = proc.memory_info().rss
        stats["memory_percent"] = proc.memory_percent()
        stats["cpu_percent"] = proc.cpu_percent(interval=0.0)
    except Exception:
        if resource is not None:
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                rss = getattr(usage, "ru_maxrss", 0)
                stats["rss_bytes"] = rss * (1024 if sys.platform != "darwin" else 1)
            except Exception:
                stats["rss_bytes"] = None
    if hasattr(os, "getloadavg"):
        try:
            stats["load_average"] = list(os.getloadavg())
        except OSError:
            stats["load_average"] = None
    return stats


def _format_stats(s: dict) -> str:
    rss = s.get("rss_bytes")
    rss_mb = f"{rss / 1_048_576:.1f} MB" if rss else "n/a"
    cpu = s.get("cpu_percent")
    cpu_str = f"{cpu:.1f}%" if cpu is not None else "n/a"
    load = s.get("load_average")
    load_str = " / ".join(f"{v:.2f}" for v in load) if load else "n/a"
    return (
        f"📊 System profile ({s.get('platform', '')})\n"
        f"   PID {s.get('pid')} · Python {s.get('python')}\n"
        f"   CPU cores: {s.get('cpu_count')}  |  CPU usage: {cpu_str}\n"
        f"   Memory (RSS): {rss_mb}\n"
        f"   Load average: {load_str}"
    )


async def run_agent(server: str) -> None:
    from mars.services.service_utils import build_hello, run_wire_agent
    await run_wire_agent(
        server,
        build_hello("svc.profiler@1", ["profiler", "profile", "performance", "memory", "cpu"]),
        lambda _: collect_stats(),
        "profile.json",
        in_executor=False,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mars-agent-profiler")
    parser.parse_args(argv)

    server = MCPServer("svc.profiler", "1.0.0")

    @server.tool(
        "get_profile",
        "Return CPU, memory, and process statistics as a human-readable summary.",
        {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Ignored; any value triggers collection"},
            },
        },
    )
    def get_profile(request: str = "") -> str:  # noqa: ARG001
        return _format_stats(collect_stats())

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
