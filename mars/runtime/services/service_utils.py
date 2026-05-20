from __future__ import annotations

import asyncio
import base64
import binascii
import importlib
import inspect
import json
import re
from pathlib import Path
from typing import Any, Callable

_DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.DOTALL)
_BASE64_CHARS_RE = re.compile(r"^[A-Za-z0-9+/\s=]+$")


# ---------------------------------------------------------------------------
# Wire-protocol helpers shared by all service agents
# ---------------------------------------------------------------------------

async def send_json(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    """Write one newline-delimited JSON frame to *writer*."""
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()


def encode_json_artifact(obj: Any) -> str:
    """Serialise *obj* as indented JSON and return a base64 ASCII string."""
    return base64.b64encode(
        json.dumps(obj, indent=2, default=str).encode("utf-8")
    ).decode("ascii")


def build_hello(name: str, skills: list[str]) -> dict[str, Any]:
    """Return a ``hello`` registration payload for a service agent."""
    return {"t": "hello", "role": "agent", "name": name, "skills": skills}


def has_module(name: str) -> bool:
    """Return True if *name* can be imported (package is installed)."""
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


async def run_wire_agent(
    server: str,
    hello: dict[str, Any],
    handler: Callable[[str], Any],
    artifact_name: str,
    *,
    require_text: bool = True,
    in_executor: bool = True,
    text_formatter: "Callable[[Any], str] | None" = None,
) -> None:
    """Connect to *server*, register, then loop dispatching ``msg`` events.

    For each ``msg`` received the *handler* is called with the message text and
    its return value is sent back as a JSON artifact named *artifact_name*.
    When *text_formatter* is provided, a human-readable ``msg`` reply is also
    sent back to the requester so the chat panel shows formatted output instead
    of raw JSON.

    Parameters
    ----------
    server:
        ``"host:port"`` string (e.g. ``"localhost:7432"``).
    hello:
        Registration payload — build with :func:`build_hello`.
    handler:
        Callable ``(text: str) -> dict``.  May be sync or async.
        Sync callables are run in the default thread-pool executor when
        *in_executor* is ``True`` (recommended for CPU/IO-bound work).
    artifact_name:
        ``name`` field of the artifact response (e.g. ``"math_result.json"``).
    require_text:
        When ``True`` (default) skip ``msg`` events whose text is empty.
    in_executor:
        Run a sync *handler* in the default thread pool (default ``True``).
        Set to ``False`` for fast, non-blocking handlers to avoid overhead.
    text_formatter:
        Optional callable ``(result: Any) -> str``.  When supplied, the return
        value is sent as a ``msg`` reply to the original requester so the chat
        panel shows a human-readable response.  The JSON artifact is still
        stored for programmatic use.
    """
    host, port = parse_server(server)
    reader, writer = await asyncio.open_connection(
        host, port, limit=16 * 1024 * 1024
    )
    await send_json(writer, hello)

    try:
        while not reader.at_eof():
            raw = await reader.readline()
            if not raw:
                break
            try:
                ev = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            if ev.get("t") != "msg":
                continue
            text = str(ev.get("text") or "").strip()
            if require_text and not text:
                continue
            from_id = str(ev.get("from") or "")

            if inspect.iscoroutinefunction(handler):
                result = await handler(text)
            elif in_executor:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, handler, text)
            else:
                result = handler(text)

            # Human-readable reply (shown in chat panel)
            if text_formatter is not None and from_id:
                try:
                    reply_text = text_formatter(result)
                except Exception as exc:  # noqa: BLE001
                    reply_text = f"(formatting error: {exc})"
                await send_json(writer, {"t": "msg", "target": from_id, "text": reply_text})

            # JSON artifact (stored for programmatic / downstream use)
            await send_json(writer, {
                "t":    "artifact",
                "name": artifact_name,
                "mime": "application/json",
                "data": encode_json_artifact(result),
            })
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass


# ---------------------------------------------------------------------------
# Existing helpers (payload parsing, file utils, etc.)
# ---------------------------------------------------------------------------


def parse_server(server: str) -> tuple[str, int]:
    host, _, port_str = server.rpartition(":")
    host = host or "localhost"
    port = int(port_str) if port_str.isdigit() else 7432
    return host, port


def is_target_message(ev: dict[str, Any], target_name: str) -> bool:
    return ev.get("t") == "msg" and str(ev.get("target") or "") == target_name


def looks_like_base64(text: str, *, min_length: int = 64) -> bool:
    compact = "".join(text.strip().split())
    if len(compact) < min_length or len(compact) % 4 != 0:
        return False
    if not _BASE64_CHARS_RE.fullmatch(compact):
        return False
    try:
        base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return False
    return True


def split_data_uri(value: str) -> tuple[str | None, str]:
    match = _DATA_URI_RE.match(value.strip())
    if not match:
        return None, value
    return match.group("mime"), match.group("data")


def decode_base64_bytes(value: str) -> bytes:
    _, payload = split_data_uri(value)
    return base64.b64decode("".join(payload.strip().split()))


def extract_payload_attachment(ev: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    attachments = ev.get("attachments", [])
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                data = item.get("data")
                if isinstance(data, str) and data:
                    return data, item.get("mime"), item.get("name")
                encoded = item.get("base64")
                if isinstance(encoded, str) and encoded:
                    return encoded, item.get("mime"), item.get("name")
            elif isinstance(item, str):
                mime, payload = split_data_uri(item)
                if mime:
                    return payload, mime, None
                if looks_like_base64(item):
                    return item, None, None
    text = ev.get("text")
    if isinstance(text, str) and text.strip():
        mime, payload = split_data_uri(text)
        if mime:
            return payload, mime, None
        if looks_like_base64(text):
            return text, None, None
        if text.lstrip().startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                data = payload.get("data")
                if isinstance(data, str) and data:
                    return data, payload.get("mime"), payload.get("name")
    return None, None, None


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def guess_extension(data: bytes, mime: str | None, *, fallback: str) -> str:
    mime = (mime or "").lower()
    if "png" in mime or data.startswith(b"\x89PNG"):
        return ".png"
    if "jpeg" in mime or "jpg" in mime or data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if "wav" in mime or data.startswith(b"RIFF"):
        return ".wav"
    if "mpeg" in mime or "mp3" in mime or data.startswith(b"ID3"):
        return ".mp3"
    if "ogg" in mime or data.startswith(b"OggS"):
        return ".ogg"
    return fallback
