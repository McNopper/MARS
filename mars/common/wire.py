"""Newline-delimited JSON wire framing shared across MARS.

MARS components (CLI client, server, federation, MCP adapter, service agents)
all speak the same transport: one JSON object per line, terminated by ``\\n``.
Historically every component hand-rolled the same two operations —
``(json.dumps(x) + "\\n").encode()`` to write and
``json.loads(await reader.readline())`` to read — at ~20 call sites.

This module centralises that framing so encoding, decoding and the edge cases
(EOF, blank lines, malformed JSON, non-serialisable values) are handled once
and identically everywhere.

The helpers come in two layers:

* **Primitives** — :func:`encode_frame` / :func:`decode_frame` are pure and
  synchronous. Use them when you already own the read/write flow (e.g. a
  ``writer.write(...)`` inside custom error handling).
* **Stream helpers** — :func:`write_frame`, :func:`read_frame` and
  :func:`iter_frames` operate on :class:`asyncio.StreamReader` /
  :class:`asyncio.StreamWriter` and encapsulate the common loop.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

__all__ = [
    "encode_frame",
    "decode_frame",
    "write_frame",
    "read_frame",
    "iter_frames",
]


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
