"""Minimal WebSocket server exposing MARS state and events to browser clients."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import shlex
from typing import Any

from mars.common.constants import DEFAULT_WS_PORT
from mars.common.models import MARSState
from mars.server.server import MARSServer

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class MARSWebSocketServer:
    def __init__(self, server: MARSServer, state: MARSState) -> None:
        self._server = server
        self._state = state
        self._clients_ws: list[asyncio.StreamWriter] = []
        self._state._event_listeners.append(self._broadcast_ws)

    def _state_dump(self) -> dict[str, Any]:
        return self._server._state_dump()

    def _send_ws_text(self, writer: asyncio.StreamWriter, text: str) -> None:
        payload = text.encode("utf-8")
        frame = bytearray([0x81])
        length = len(payload)
        if length < 126:
            frame.append(length)
        elif length < (1 << 16):
            frame.append(126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(127)
            frame.extend(length.to_bytes(8, "big"))
        writer.write(bytes(frame) + payload)

    def _broadcast_ws(self, ev: dict[str, Any]) -> None:
        data = json.dumps(ev, default=str)
        dead: list[asyncio.StreamWriter] = []
        for writer in list(self._clients_ws):
            try:
                if writer.is_closing():
                    raise ConnectionError("client closed")
                self._send_ws_text(writer, data)
            except Exception:
                dead.append(writer)
        for writer in dead:
            if writer in self._clients_ws:
                self._clients_ws.remove(writer)
            with contextlib.suppress(Exception):
                writer.close()

    _WS_MAX_PAYLOAD = 4 * 1024 * 1024

    async def _read_ws_frame(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str | None:
        first, second = await reader.readexactly(2)
        opcode = first & 0x0F
        masked = (second & 0x80) != 0
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(await reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await reader.readexactly(8), "big")
        if length > self._WS_MAX_PAYLOAD:
            writer.write(b"\x88\x02\x03\xF0")
            with contextlib.suppress(Exception):
                await writer.drain()
            return None
        mask = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 8:
            return None
        if opcode == 9:
            writer.write(b"\x8A\x00")
            return ""
        if opcode != 1:
            return ""
        return payload.decode("utf-8", errors="ignore")

    async def handle_ws_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode("utf-8", errors="ignore").split("\r\n")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            key = headers.get("sec-websocket-key")
            if not key:
                raise ValueError("missing websocket key")
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("utf-8")).digest()).decode("ascii")
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            )
            writer.write(response.encode("utf-8"))
            await writer.drain()
            self._clients_ws.append(writer)
            self._send_ws_text(writer, json.dumps(self._state_dump(), default=str))
            current_agent: str | None = None
            while True:
                data = await self._read_ws_frame(reader, writer)
                if data is None:
                    break
                if not data:
                    continue
                try:
                    msg = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("t")
                if mtype == "hello":
                    current_agent = msg.get("current_agent") or current_agent
                elif mtype == "cmd":
                    text = str(msg.get("text") or "")
                    if text.startswith("/switch"):
                        parts = text.split(maxsplit=1)
                        current_agent = parts[1].strip() if len(parts) > 1 else None
                        self._send_ws_text(writer, json.dumps({"t": "switch", "current_agent": current_agent}))
                    else:
                        try:
                            if text.startswith("/spawn"):
                                status = await self._server._spawn_from_tokens(shlex.split(text)[1:])
                            else:
                                status = f"Unsupported server command: {text}"
                        except Exception as exc:
                            status = str(exc)
                        self._send_ws_text(writer, json.dumps({"t": "status", "text": status, "style": "bold cyan"}))
                elif mtype == "msg":
                    text = str(msg.get("text") or "")
                    target = str(msg.get("target") or current_agent or "")
                    if not target:
                        self._send_ws_text(
                            writer,
                            json.dumps({"t": "status", "text": "No target agent selected", "style": "bold red"}),
                        )
                        continue
                    await self._server.route_external_message("ws-client", target, text)
        finally:
            if writer in self._clients_ws:
                self._clients_ws.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def serve(self, host: str, port: int = DEFAULT_WS_PORT) -> None:
        server = await asyncio.start_server(self.handle_ws_client, host, port)
        async with server:
            await server.serve_forever()
