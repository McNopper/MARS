"""mars-server entry point: argument parsing and async orchestration."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import socket
import sys
from pathlib import Path

import httpx

from mars.cli.utils import _load_dotenv
from mars.common.constants import DEFAULT_HTTP_PORT, DEFAULT_WS_PORT
from mars.common.models import (
    DEFAULT_FEDERATION_PORT,
    DEFAULT_PORT,
    MARSState,
)
from mars.server.audit import MARSAuditLog
from mars.server.federation import FederationManager
from mars.server.payloads import _agent_payload, _scope_payload
from mars.server.rest import MARSRestAPI
from mars.server.server import ClientSession, MARSServer
from mars.server.service_manager import _auto_spawn_free_providers
from mars.server.services.llm.copilot import _get_token as _copilot_token
from mars.server.storage.scopes.store import ScopeStore
from mars.server.ws import MARSWebSocketServer

__all__ = [
    "ClientSession",
    "MARSServer",
    "MARSRestAPI",
    "MARSWebSocketServer",
    "MARSAuditLog",
    "_agent_payload",
    "_scope_payload",
    "main",
]


async def _async_server(args: argparse.Namespace) -> None:
    def _suppress_connection_reset(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        loop.default_exception_handler(context)

    asyncio.get_running_loop().set_exception_handler(_suppress_connection_reset)

    state = MARSState(platform_name="mars-server")
    scope_store = ScopeStore(Path("scopes"))
    state.scopes = scope_store.load_all()

    audit = MARSAuditLog(
        getattr(args, "audit", "mars_audit.jsonl"),
        verbose=getattr(args, "audit_verbose", False),
    )
    state._event_listeners.append(audit.log)

    mars_server = MARSServer(state)
    mars_server.attach_audit(audit)
    cors_raw = getattr(args, "cors_allow", None)
    cors_list = [origin.strip() for origin in cors_raw.split(",")] if cors_raw else []
    rest_api = MARSRestAPI(mars_server, state, cors_allow=cors_list)
    ws_server = MARSWebSocketServer(mars_server, state)

    tcp_ready = asyncio.get_running_loop().create_future()
    tcp_task = asyncio.create_task(mars_server.serve(args.host, args.port, ready_future=tcp_ready))
    rest_task = asyncio.create_task(rest_api.serve(args.host, args.http_port))
    ws_task = asyncio.create_task(ws_server.serve(args.host, args.ws_port))
    await tcp_ready

    # Federation: peer with other MARS nodes so their agents/skills/models pool.
    # Node id must be unique across the federation; default includes the hostname
    # so two nodes on different hosts (even on the same port) never collide.
    node_id = getattr(args, "node_id", None) or f"{socket.gethostname()}:{args.port}"
    federation = FederationManager(mars_server, node_id=node_id)
    mars_server.attach_federation(federation)
    fed_task = asyncio.create_task(federation.serve(args.host, args.federation_port))
    peers = list(getattr(args, "peer", None) or []) + list(getattr(args, "connect", None) or [])
    for entry in peers:
        if ":" in entry:
            phost, _, pport_s = entry.rpartition(":")
            try:
                pport = int(pport_s)
            except ValueError:
                phost, pport = entry, DEFAULT_FEDERATION_PORT
        else:
            phost, pport = entry, DEFAULT_FEDERATION_PORT
        asyncio.create_task(federation.connect(phost, pport))

    server_host = "localhost" if args.host in ("0.0.0.0", "::") else args.host
    server_addr = f"{server_host}:{args.port}"
    _auto_spawn_free_providers(server_addr)
    await mars_server.start_mcp_agents()

    async def _ollama_reachable(host: str = "http://localhost:11434") -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{host.rstrip('/')}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    if args.provider:
        providers = list(args.provider)
    else:
        ollama_host = getattr(args, "ollama_host", None) or "http://localhost:11434"
        if await _ollama_reachable(ollama_host):
            providers = ["ollama"]
            print("🦙 Ollama detected — spawning Ollama LLM agent (use --provider to override)", flush=True)
        elif _copilot_token(getattr(args, "key", None)):
            providers = ["copilot"]
            print("🤖 Copilot token detected — spawning Copilot LLM agent", flush=True)
        else:
            providers = []

    for provider in providers:
        cmd = mars_server._build_wire_agent_cmd(
            server_addr,
            provider=provider,
            model=args.model if (getattr(args, "model", None) and len(providers) == 1) else None,
            api_key=getattr(args, "key", None),
            host=args.ollama_host if (provider == "ollama" and getattr(args, "ollama_host", None)) else None,
        )
        mars_server._spawn_subprocess(cmd)

    print(f"🤖 MARS Server ready — {len(state.agents)} agents", flush=True)
    print(f"   TCP  :  {args.host}:{args.port}", flush=True)
    print(f"   REST :  http://{args.host}:{args.http_port}", flush=True)
    print(f"   WS   :  ws://{args.host}:{args.ws_port}", flush=True)
    print(f"   Fed  :  {args.host}:{args.federation_port}", flush=True)
    print(f"   Audit:  {args.audit}", flush=True)


    try:
        await asyncio.gather(tcp_task, rest_task, ws_task, fed_task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await mars_server.stop_mcp_agents()
        audit.close()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")
    _load_dotenv()
    parser = argparse.ArgumentParser(prog="mars-server", description="MARS headless TCP router")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Interface to bind TCP / REST / WebSocket listeners on. Defaults to "
            "127.0.0.1 (loopback only) to keep an unauthenticated server off the "
            "network."
        ),
    )
    parser.add_argument(
        "--cors-allow",
        default=None,
        help="Comma-separated list of origins allowed by the REST API",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--federation-port", type=int, default=DEFAULT_FEDERATION_PORT, dest="federation_port")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, dest="http_port")
    parser.add_argument("--ws-port", type=int, default=DEFAULT_WS_PORT, dest="ws_port")
    parser.add_argument("--provider", nargs="+", default=None, help="LLM service(s) to spawn on startup")
    parser.add_argument("--model", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--ollama-host", default=None, dest="ollama_host", help="Ollama server URL")
    parser.add_argument(
        "--peer",
        nargs="*",
        default=None,
        metavar="HOST[:PORT]",
        help="Federate with one or more peer MARS nodes on startup (federation port)",
    )
    parser.add_argument("--connect", nargs="*", default=None, metavar="HOST[:PORT]", help="Alias for --peer")
    parser.add_argument(
        "--node-id",
        default=None,
        dest="node_id",
        help="Unique federation node id (default: <hostname>:<port>)",
    )
    parser.add_argument("--audit", default="mars_audit.jsonl")
    parser.add_argument(
        "--audit-verbose",
        action="store_true",
        dest="audit_verbose",
        help="Log full wire frames (complete message text, tool calls, tool results) to the audit file",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(_async_server(args))


if __name__ == "__main__":
    main()
