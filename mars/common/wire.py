"""Wire framing for MARS — legacy JSON-line and multi-protocol.

MARS speaks one transport: newline-delimited JSON.  All components share the
same primitives so encoding, decoding, and edge-cases (EOF, malformed JSON,
non-serialisable values) are handled once.

The module has two layers:

* **Legacy (default)** — one JSON object per line; used by the TCP bus between
  the server and CLI/LLM clients.
* **Multi-protocol** — an optional magic-header prefix that identifies the
  protocol before the JSON payload, used when multiple named protocols share
  the same transport (AG-UI, A2A, MCP, MARS federation).

``WireProtocol`` and the multi-protocol helpers live here so that *both* the
server and the CLI can import them without introducing circular dependencies
(``common`` must never import from ``server``).  Cross-protocol type
conversions that require ``ProtocolType`` from ``mars.server.protocols.base``
live in that module instead.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from enum import Enum
from typing import Any, Optional

__all__ = [
    "WireProtocol",
    "PROTOCOL_MAGIC_HEADERS",
    "encode_frame",
    "decode_frame",
    "encode_frame_with_protocol",
    "decode_frame_with_protocol",
    "detect_protocol_from_data",
    "write_frame",
    "read_frame",
    "iter_frames",
]


class WireProtocol(Enum):
    """Named wire-level protocols that prefix their frames with a magic header."""
    AG_UI = "ag_ui"   # AG-UI — human↔agent interaction
    A2A   = "a2a"     # A2A   — agent↔agent task delegation
    MCP   = "mcp"     # MCP   — tool/resource access
    MARS  = "mars"    # MARS  — server federation


# Magic header bytes: ``detect_protocol_from_data`` scans these in order.
PROTOCOL_MAGIC_HEADERS: dict[WireProtocol, bytes] = {
    WireProtocol.AG_UI: b"AG-UI/",
    WireProtocol.A2A:   b"A2A-JSONRPC/",
    WireProtocol.MCP:   b"MCP-STDIO/",
    WireProtocol.MARS:  b"MARS-FED/",
}


def detect_protocol_from_data(data: bytes | bytearray) -> WireProtocol:
    """Return the ``WireProtocol`` whose magic header *data* starts with.

    Raises :class:`ValueError` when *data* is empty or no header matches.
    """
    if not data:
        raise ValueError("Cannot detect protocol from empty data")
    for protocol, header in PROTOCOL_MAGIC_HEADERS.items():
        if data.startswith(header):
            return protocol
    raise ValueError("Unknown protocol — no recognised magic header in data")


def encode_frame_with_protocol(
    payload: Any,
    protocol: WireProtocol,
    *,
    protocol_version: Optional[str] = None,
    default: Callable[[Any], Any] | None = str,
) -> bytes:
    """Serialise *payload* with the named protocol's magic-header framing.

    Format on the wire::

        MAGIC_HEADER/<version>\\n
        <json>\\n

    Two ``readline()`` calls are needed to read one such frame; the server
    reads the header line first, detects the protocol, then reads the JSON.
    """
    header = PROTOCOL_MAGIC_HEADERS.get(protocol)
    if header is None:
        raise ValueError(f"Unsupported protocol: {protocol!r}")
    version = protocol_version or "1.0.0"
    json_str = json.dumps(payload, default=default)
    return f"{header.decode()}{version}\n{json_str}\n".encode("utf-8")


def decode_frame_with_protocol(
    raw: bytes | bytearray,
) -> tuple[WireProtocol, dict[str, Any]]:
    """Decode a magic-header framed message produced by :func:`encode_frame_with_protocol`.

    *raw* should contain the full two-line frame (header line + JSON line).
    Returns ``(protocol, message_dict)``.

    Raises :class:`ValueError` on any parse failure.
    """
    if not raw:
        raise ValueError("Cannot decode empty data")
    protocol = detect_protocol_from_data(raw)
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"UTF-8 decode error: {exc}") from exc
    lines = text.split("\n", 2)
    if len(lines) < 2 or not lines[1].strip():
        raise ValueError(f"Invalid {protocol.value} frame: expected header line + JSON line")
    try:
        obj = json.loads(lines[1].strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"JSON decode error in {protocol.value} frame: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"{protocol.value} frame payload must be a JSON object")
    return protocol, obj


def encode_frame(payload: Any, *, default: Callable[[Any], Any] | None = str) -> bytes:
    """Serialise *payload* as one newline-terminated UTF-8 JSON frame.

    ``default`` is passed to :func:`json.dumps` so values that are not natively
    serialisable (e.g. ``datetime``) are stringified rather than raising. Pass
    ``default=None`` to restore strict behaviour.
    """
    return (json.dumps(payload, default=default) + "\n").encode("utf-8")


def decode_frame(raw: bytes | bytearray | str, *, require_dict: bool = True) -> dict[str, Any] | None:
    """Decode one wire frame, returning ``None`` for anything unusable.

    Returns ``None`` when *raw* is empty/blank, is not valid JSON, or (when
    *require_dict* is true) does not decode to a JSON object. This mirrors the
    "skip and continue" semantics of every existing read loop.
    """
    if isinstance(raw, (bytes, bytearray)):
        if not raw:
            return None
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = raw
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    if require_dict and not isinstance(obj, dict):
        return None
    return obj


async def write_frame(
    writer: asyncio.StreamWriter,
    payload: Any,
    *,
    default: Callable[[Any], Any] | None = str,
    drain: bool = True,
) -> bool:
    """Write one frame to *writer*; return ``True`` if it was handed off.

    Returns ``False`` (instead of raising) when the transport is already
    closing or the write fails, so callers can treat a dead peer as a no-op.
    When *drain* is true the write is flushed; drain errors are suppressed.
    """
    try:
        if writer.is_closing():
            return False
        writer.write(encode_frame(payload, default=default))
    except Exception:
        return False
    if drain:
        try:
            await writer.drain()
        except Exception:
            return False
    return True


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read the next valid JSON object frame, or ``None`` at end of stream.

    Blank or malformed lines are skipped; the call only returns ``None`` once
    the underlying stream reaches EOF.
    """
    while not reader.at_eof():
        raw = await reader.readline()
        if not raw:
            return None
        frame = decode_frame(raw)
        if frame is None:
            continue
        return frame
    return None


async def iter_frames(reader: asyncio.StreamReader) -> AsyncIterator[dict[str, Any]]:
    """Yield decoded object frames from *reader* until the stream ends."""
    while True:
        frame = await read_frame(reader)
        if frame is None:
            return
        yield frame
