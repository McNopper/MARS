"""MARS Clock Service Agent — provides current time and node location.

Any agent can query this service to get the node's current datetime and
geographic location without needing direct network access.

Usage (after /switch svc.clock@1)
-----------------------------------
  (any message)   → returns clock.json with time + location data

Response fields
---------------
  timestamp       ISO-8601 UTC timestamp
  local_time      Local wall-clock time (HH:MM:SS)
  local_date      Local date (YYYY-MM-DD)
  utc_offset      Offset from UTC as ±HH:MM string
  timezone        IANA timezone name (from geolocation, if available)
  ip              Public IP of this node
  city            City name (or null)
  country         Country name (or null)
  country_code    ISO 3166-1 alpha-2 code (or null)
  lat / lon       Latitude / Longitude (or null)
  isp             ISP / organisation name (or null)
  geo_source      Which backend provided the location data
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any

from mars.runtime.services.mcp_server import MCPServer


_GEO_TIMEOUT = 8


# ---------------------------------------------------------------------------
# Geolocation (fetched once at startup, then cached)
# ---------------------------------------------------------------------------

def _fetch_geo() -> dict[str, Any]:
    """Return location data from ip-api.com with ipinfo.io fallback."""
    # Primary: ip-api.com
    try:
        with urllib.request.urlopen("http://ip-api.com/json", timeout=_GEO_TIMEOUT) as r:
            d = json.loads(r.read())
        if d.get("status") == "success":
            return {
                "ip":           d.get("query"),
                "city":         d.get("city"),
                "country":      d.get("country"),
                "country_code": d.get("countryCode"),
                "lat":          d.get("lat"),
                "lon":          d.get("lon"),
                "timezone":     d.get("timezone"),
                "isp":          d.get("isp"),
                "geo_source":   "ip-api.com",
            }
    except Exception:
        pass

    # Fallback: ipinfo.io
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=_GEO_TIMEOUT) as r:
            d = json.loads(r.read())
        lat, lon = None, None
        if "loc" in d:
            parts = d["loc"].split(",")
            if len(parts) == 2:
                try:
                    lat, lon = float(parts[0]), float(parts[1])
                except ValueError:
                    pass
        return {
            "ip":           d.get("ip"),
            "city":         d.get("city"),
            "country":      None,
            "country_code": d.get("country"),
            "lat":          lat,
            "lon":          lon,
            "timezone":     d.get("timezone"),
            "isp":          d.get("org"),
            "geo_source":   "ipinfo.io",
        }
    except Exception:
        pass

    return {
        "ip": None, "city": None, "country": None, "country_code": None,
        "lat": None, "lon": None, "timezone": None, "isp": None,
        "geo_source": "offline",
    }


def _build_snapshot(geo: dict[str, Any]) -> dict[str, Any]:
    """Assemble the full clock+location payload for the current moment."""
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now()
    offset_secs = (now_local - now_utc.replace(tzinfo=None)).total_seconds()
    offset_td = timedelta(seconds=round(offset_secs / 60) * 60)
    sign = "+" if offset_td.total_seconds() >= 0 else "-"
    total_minutes = int(abs(offset_td.total_seconds()) // 60)
    utc_offset = f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"

    return {
        "timestamp":    now_utc.isoformat(),
        "local_time":   now_local.strftime("%H:%M:%S"),
        "local_date":   now_local.strftime("%Y-%m-%d"),
        "utc_offset":   utc_offset,
        **geo,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="mars-agent-clock",
        description="MARS clock + location MCP service agent",
    )
    parser.parse_args(argv)

    geo = _fetch_geo()
    server = MCPServer("svc.clock", "1.0.0")

    @server.tool(
        "get_time",
        "Return the current date/time and node geolocation as a human-readable summary.",
        {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Ignored; any value triggers the snapshot"},
            },
        },
    )
    def get_time(request: str = "") -> str:  # noqa: ARG001
        s = _build_snapshot(geo)
        city = s.get("city") or ""
        country = s.get("country") or ""
        location = ", ".join(filter(None, [city, country])) or "unknown location"
        tz = s.get("timezone") or s.get("utc_offset") or "UTC"
        return (
            f"🕐 Local time: {s['local_time']}  ({s['local_date']})\n"
            f"   Timezone:   {tz}  (UTC{s['utc_offset']})\n"
            f"   Location:   {location}\n"
            f"   Node IP:    {s.get('ip') or 'unknown'}"
        )

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
