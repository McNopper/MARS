"""MARS URL Service Agent — fetches URLs and returns content as artifacts.

Accepts a URL (or a JSON command) and performs an HTTP GET (or POST).
The response body is returned as an artifact — text content as UTF-8,
binary content as base64.  A plain-text summary is always included in
the JSON so an LLM can read the result without decoding anything.

Supported input formats
-----------------------
  Bare URL:    ``https://example.com``
  Plain text:  ``fetch https://example.com``
               ``get https://api.example.com/data``
               ``post https://api.example.com/data {"key": "value"}``
  JSON object: ``{"url": "https://example.com"}``
               ``{"url": "...", "method": "POST", "body": "...",
                  "headers": {"X-Token": "..."}, "timeout": 10}``

Response fields (JSON artifact)
---------------------------------
  url             Final URL after redirects
  method          HTTP method used
  status          HTTP status code (int)
  ok              true if status 2xx
  content_type    Content-Type header (normalised)
  size            Response body size in bytes
  text            Decoded text body (for text/* and application/json)
  data            Base64-encoded body (for binary content types)
  headers         Selected response headers (dict)
  error           Error message (only present on failure)

Security
--------
  Private / link-local addresses (127.x, 10.x, 192.168.x, 169.254.x,
  [::1], fc00::/7) are blocked unless ``--allow-private`` is passed.
  Maximum response size: 4 MB (configurable with ``--max-bytes``).
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mars.services.mcp_server import MCPServer


_DEFAULT_TIMEOUT = 15.0
_DEFAULT_MAX_BYTES = 4 * 1024 * 1024  # 4 MB

# Content types treated as text (returned in "text" field, not base64)
_TEXT_TYPES = re.compile(
    r"(text/|application/(json|xml|xhtml|javascript|x-www-form-urlencoded)"
    r"|application/.*\+xml|application/.*\+json)",
    re.IGNORECASE,
)

# Private / link-local ranges to block
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private / loopback address."""
    try:
        addr = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(addr)
        return any(ip in net for net in _PRIVATE_NETS)
    except (socket.gaierror, ValueError):
        return False


def _selected_headers(raw: Any) -> dict[str, str]:
    """Return a subset of response headers that are useful to an LLM."""
    keep = {
        "content-type", "content-length", "last-modified", "etag",
        "x-ratelimit-limit", "x-ratelimit-remaining", "x-request-id",
        "cache-control", "server",
    }
    out: dict[str, str] = {}
    if hasattr(raw, "items"):
        for k, v in raw.items():
            if k.lower() in keep:
                out[k.lower()] = v
    return out


def fetch_url(
    url: str,
    *,
    method: str = "GET",
    body: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    allow_private: bool = False,
) -> dict[str, Any]:
    """Perform the HTTP request synchronously and return a result dict."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""

    if not allow_private and _is_private(hostname):
        return {
            "url": url, "method": method, "ok": False,
            "error": f"blocked: {hostname!r} resolves to a private address",
        }

    headers: dict[str, str] = {
        "User-Agent": "MARS-URL-Agent/1.0",
        "Accept": "*/*",
    }
    if extra_headers:
        headers.update(extra_headers)

    data: bytes | None = body.encode("utf-8") if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_content_type = resp.headers.get("Content-Type", "")
            content_type = raw_content_type.split(";")[0].strip()
            selected = _selected_headers(resp.headers)

            body_bytes = resp.read(max_bytes + 1)
            truncated = len(body_bytes) > max_bytes
            if truncated:
                body_bytes = body_bytes[:max_bytes]

            result: dict[str, Any] = {
                "url": resp.url,
                "method": method.upper(),
                "status": resp.status,
                "ok": 200 <= resp.status < 300,
                "content_type": content_type,
                "size": len(body_bytes),
                "headers": selected,
            }
            if truncated:
                result["truncated"] = True
                result["max_bytes"] = max_bytes

            if _TEXT_TYPES.match(content_type):
                charset = "utf-8"
                m = re.search(r"charset=([^\s;]+)", raw_content_type, re.I)
                if m:
                    charset = m.group(1).strip('"')
                try:
                    result["text"] = body_bytes.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    result["text"] = body_bytes.decode("utf-8", errors="replace")
            else:
                result["data"] = base64.b64encode(body_bytes).decode("ascii")

            return result

    except urllib.error.HTTPError as exc:
        return {
            "url": url, "method": method.upper(),
            "status": exc.code, "ok": False,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        return {
            "url": url, "method": method.upper(), "ok": False,
            "error": str(exc.reason),
        }
    except OSError as exc:
        return {"url": url, "method": method.upper(), "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Request parser
# ---------------------------------------------------------------------------

def _parse_request(
    text: str,
    *,
    allow_private: bool = False,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Parse *text* (plain or JSON) and call fetch_url."""
    text = text.strip()

    # JSON object: {"url": "...", "method": "...", "body": "...", ...}
    if text.startswith("{"):
        try:
            cmd = json.loads(text)
            url = str(cmd.get("url", "")).strip()
            if not url:
                return {"ok": False, "error": "JSON command missing 'url' field"}
            return fetch_url(
                url,
                method=str(cmd.get("method", "GET")),
                body=cmd.get("body"),
                extra_headers=cmd.get("headers"),
                timeout=float(cmd.get("timeout", timeout)),
                max_bytes=int(cmd.get("max_bytes", max_bytes)),
                allow_private=allow_private,
            )
        except json.JSONDecodeError:
            pass  # fall through

    # Plain text: "[method] <url> [body]"
    parts = text.split(None, 2)
    if not parts:
        return {"ok": False, "error": "empty request"}

    first = parts[0].upper()
    if first in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
                 "FETCH"):
        method = "GET" if first == "FETCH" else first
        url = parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else None
    else:
        method = "GET"
        url = parts[0]
        body = None

    if not url:
        return {"ok": False, "error": "no URL provided"}

    return fetch_url(
        url,
        method=method,
        body=body,
        timeout=timeout,
        max_bytes=max_bytes,
        allow_private=allow_private,
    )


# ---------------------------------------------------------------------------
# Agent wire loop
# ---------------------------------------------------------------------------

async def run_agent(
    server: str,
    *,
    allow_private: bool = False,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    timeout: float = _DEFAULT_TIMEOUT,
) -> None:
    from mars.services.service_utils import build_hello, run_wire_agent
    def _handler(text: str) -> dict[str, Any]:
        return _parse_request(
            text,
            allow_private=allow_private,
            max_bytes=max_bytes,
            timeout=timeout,
        )

    await run_wire_agent(
        server,
        build_hello("svc.url@1", [
            "url", "fetch", "http", "web", "get", "post",
            "request", "download", "browse",
        ]),
        _handler,
        "url_result.json",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-url",
        description="MARS URL fetch MCP service agent",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        default=False,
        help="Allow fetching private/loopback addresses (disabled by default)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=_DEFAULT_MAX_BYTES,
        help="Maximum response body size in bytes (default: 4 MB)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT,
        help="HTTP request timeout in seconds (default: 15)",
    )
    args = parser.parse_args(argv)

    allow_private = args.allow_private
    max_bytes = args.max_bytes
    timeout = args.timeout

    server = MCPServer("svc.url", "1.0.0")

    @server.tool(
        "fetch_url",
        "Fetch the content of a URL via HTTP GET or POST and return it as JSON. "
        "Accepts a URL string or a JSON object with keys 'url', 'method', 'headers', 'body'.",
    )
    def fetch_url(request: str) -> dict:
        return _parse_request(request, allow_private=allow_private, max_bytes=max_bytes, timeout=timeout)

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
