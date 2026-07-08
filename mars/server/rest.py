"""HTTP REST + A2A JSON-RPC front-end for a MARSServer."""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any

from mars.common.constants import A2A_CARD_PATH, DEFAULT_HTTP_PORT
from mars.common.models import MARSState
from mars.server.payloads import _agent_payload, _scope_payload
from mars.server.server import MARSServer
from mars.server.services.a2a.adapter import build_mars_agent_card


class MARSRestAPI:
    def __init__(self, server: MARSServer, state: MARSState, cors_allow: list[str] | None = None) -> None:
        self._server = server
        self._state = state
        self._cors_allow = list(cors_allow or [])
        self._http_host: str = "127.0.0.1"
        self._http_port: int = DEFAULT_HTTP_PORT

    async def _route(self, method: str, path: str, body: bytes) -> tuple[str, Any]:
        clean_path = path.split("?", 1)[0]
        if method == "OPTIONS":
            return "200 OK", {}
        if method == "GET" and clean_path == "/":
            return "200 OK", {
                "service": "MARS REST API",
                "endpoints": [
                    "GET /", "GET /agents", "POST /spawn", "POST /message",
                    f"GET {A2A_CARD_PATH}", "POST /a2a",
                ],
            }
        if method == "GET" and clean_path == A2A_CARD_PATH:
            node_name = getattr(self._state, "platform_name", "MARS")
            host = self._http_host if self._http_host not in ("0.0.0.0", "::") else "127.0.0.1"
            base_url = f"http://{host}:{self._http_port}/a2a"
            return "200 OK", build_mars_agent_card(node_name, base_url)
        if method == "POST" and clean_path == "/a2a":
            return await self._handle_a2a_rpc(body)
        if method == "GET" and clean_path == "/agents":
            return "200 OK", [_agent_payload(rec, self._state) for rec in self._state.agents.values()]
        if method == "GET" and clean_path == "/scopes":
            return "200 OK", [_scope_payload(scope) for scope in self._state.scopes]
        if method == "GET" and clean_path == "/problems":
            return "200 OK", []
        if method == "POST" and clean_path == "/spawn":
            payload = json.loads(body.decode("utf-8") or "{}")
            provider = payload.get("provider")
            if not provider:
                return "400 Bad Request", {"ok": False, "error": "provider required"}
            args = [str(provider)]
            if payload.get("model"):
                args.append(str(payload["model"]))
            if payload.get("name"):
                args += ["--name", str(payload["name"])]
            if payload.get("key"):
                args += ["--key", str(payload["key"])]
            if payload.get("host"):
                args += ["--host", str(payload["host"])]
            status = await self._server._spawn_from_tokens(args)
            return "200 OK", {"ok": True, "status": status}
        if method == "POST" and clean_path == "/message":
            payload = json.loads(body.decode("utf-8") or "{}")
            target = payload.get("to")
            text = payload.get("text")
            if not target or text is None:
                return "400 Bad Request", {"ok": False, "error": "to and text required"}
            await self._server.route_external_message("rest-api", str(target), str(text))
            return "200 OK", {"ok": True}
        return "404 Not Found", {"ok": False, "error": "not found"}

    async def _handle_a2a_rpc(self, body: bytes) -> tuple[str, Any]:
        """Handle an A2A JSON-RPC 2.0 request (POST /a2a).

        Supports ``message/send``: extracts the text from the request message,
        dispatches it to the first available LLM agent, and returns the reply
        wrapped in an A2A Task result.
        """
        try:
            req = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return "400 Bad Request", {"ok": False, "error": "invalid JSON"}
        rpc_id = req.get("id", "1")
        method = req.get("method", "")
        params = req.get("params", {})

        if method != "message/send":
            return "200 OK", {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        # Extract text from the A2A message parts
        message = params.get("message", {})
        parts = message.get("parts", [])
        text = " ".join(
            p.get("text", "") for p in parts
            if isinstance(p, dict) and p.get("kind", p.get("type", "")) == "text"
        ).strip() or json.dumps(params)

        # Find the first available LLM agent to handle the request
        target = next(
            (aid for aid, rec in self._state.agents.items()
             if getattr(rec, "agent_type", "") == "LLMAgent"),
            None,
        )
        if target is None:
            task_result = {
                "id": str(uuid.uuid4()),
                "status": {"state": "completed"},
                "artifacts": [{
                    "parts": [{"kind": "text", "text": "No LLM agent available on this MARS node."}],
                }],
            }
        else:
            # Use a Future to capture the reply
            reply_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

            def _capture_reply(ev: dict) -> None:
                if (ev.get("t") in ("reply", "chat")
                        and ev.get("from_id") == target
                        and not reply_future.done()):
                    reply_future.set_result(ev.get("text", ""))

            self._state._event_listeners.append(_capture_reply)
            try:
                await self._server.route_external_message("a2a-rpc", target, text)
                try:
                    reply_text = await asyncio.wait_for(reply_future, timeout=30.0)
                except TimeoutError:
                    reply_text = "(timeout waiting for LLM reply)"
            finally:
                with contextlib.suppress(Exception):
                    self._state._event_listeners.remove(_capture_reply)

            task_result = {
                "id": str(uuid.uuid4()),
                "status": {"state": "completed"},
                "artifacts": [{
                    "parts": [{"kind": "text", "text": reply_text}],
                }],
            }

        return "200 OK", {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": task_result,
        }

    async def handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status = "500 Internal Server Error"
        payload: Any = {"ok": False, "error": "internal error"}
        headers: dict[str, str] = {}
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            header_block, _, body = head.partition(b"\r\n\r\n")
            lines = header_block.decode("utf-8", errors="ignore").split("\r\n")
            request_line = lines[0]
            parts = request_line.split()
            if len(parts) < 2:
                raise ValueError("invalid request")
            method, path = parts[0], parts[1]
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            content_length = int(headers.get("content-length", "0") or "0")
            if content_length > len(body):
                body += await reader.readexactly(content_length - len(body))
            status, payload = await self._route(method, path, body)
        except asyncio.IncompleteReadError:
            status, payload = "400 Bad Request", {"ok": False, "error": "incomplete request"}
        except json.JSONDecodeError:
            status, payload = "400 Bad Request", {"ok": False, "error": "invalid json"}
        except Exception as exc:
            status, payload = "400 Bad Request", {"ok": False, "error": str(exc)}
        body_bytes = json.dumps(payload, default=str).encode("utf-8")
        cors_headers = ""
        if self._cors_allow:
            origin_header = headers.get("origin", "")
            if "*" in self._cors_allow:
                allow_origin = "*"
            elif origin_header and origin_header in self._cors_allow:
                allow_origin = origin_header
            else:
                allow_origin = ""
            if allow_origin:
                cors_headers = (
                    f"Access-Control-Allow-Origin: {allow_origin}\r\n"
                    "Access-Control-Allow-Headers: Content-Type\r\n"
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                )
                if allow_origin != "*":
                    cors_headers += "Vary: Origin\r\n"
        response = (
            f"HTTP/1.1 {status}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"{cors_headers}"
            "Connection: close\r\n\r\n"
        ).encode() + body_bytes
        writer.write(response)
        try:
            await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def serve(self, host: str, port: int = DEFAULT_HTTP_PORT) -> None:
        self._http_host = host
        self._http_port = port
        server = await asyncio.start_server(self.handle_http, host, port)
        async with server:
            await server.serve_forever()
