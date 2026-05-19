"""MARS interactive terminal – fully asynchronous multi-agent TUI.

Layout (live, redraws at ~8 Hz)
---------------------------------

  ╭─ Activity Feed ─────────────────────────────────────────────────────╮
  │ ✋ 16:02  mock-agent raised hand (reply ready)                       │
  │ 🔄 16:01  mock-agent: THINKING                                       │
  │ 💬 16:00  cli-user → mock-agent  "what is 2+2?"                     │
  ╰─────────────────────────────────────────────────────────────────────╯
  ╭─ MARS · platform-alpha ──────────── Agents: 2 ──────────────────────╮
  │  ╭─────────────────╮  ╭─────────────────╮                           │
  │  │ 🤖 mock-agent   │  │ 🖥️ cli-user      │                          │
  │  │ llm.mock ◀      │  │ human            │                          │
  │  │ THINKING        │  │ —                │                          │
  │  │ ✋ reply ready  │  │                  │                          │
  │  ╰─────────────────╯  ╰─────────────────╯                          │
  ╰─────────────────────────────────────────────────────────────────────╯
  ╭─ ✋ mock-agent ──────────────────────────────────────────────────────╮
  │  The answer is 4.                                                    │
  ╰─────────────────────────────────────────────────────────────────────╯
  ─────────────────────────────────────────────────────────────────────
  [mock-agent | IDLE]> solve this together▌

Interaction model
-----------------
  • Type freely — messages are sent fire-and-forget; you keep chatting.
  • When an agent has a result its tile border turns yellow (reply ready).
  • Use /read (or /switch to that agent) to acknowledge and see the reply.
  • Multiple agents can be THINKING simultaneously.

Agent type icons (sidebar & tiles)
-----------------------------------
  🤖  LLMAgent        📡  SensorAgent      🖥️  CLIBridgeAgent
  🔧  ServiceAgent    🌉  BridgeAgent      👤  Generic Agent    📢  Verbose (auto-print)
  👽  Suspicious      👾  Blocked

Sidebar status dot  ●
----------------------
  🟢 green   IDLE — agent is ready to receive a message
  🔵 blue    THINKING — agent is actively processing (working)
  🟡 yellow  REPLY READY — agent has a response waiting (/read to view)
  🔴 red     ERROR — agent crashed, failed, or is blocked
  ⚫ grey    Other state (spawning, despawning …)

Tile border colours (full TUI mode)
------------------------------------
  green   Ready to receive (IDLE)    blue    Thinking (working)
  yellow  Reply ready                red     Error / crashed
  grey    Other state

Commands
--------
  /spawn <provider> [model]   Spawn a new LLM agent (github-models, openai, ollama, mock, …)
  /spawn screenshot           Spawn the screenshot service agent
  /spawn <provider> [model]   Spawn an LLM agent
                              Options: --name NAME --role ROLE --goal GOAL
                                       --behaviour reactive|proactive
                                       --key KEY --host HOST
  /spawn status               Spawn the status service agent
  /stop [agent_id]            Stop an agent (defaults to current)
  /read [agent_id]            Read pending reply (default: current agent)
  /verbose [agent_id]         Toggle auto-print replies for an agent
  /avatar [n|emoji]           Pick your human avatar (no args = show gallery)
  /agents                     List active agents
  /agents available           List all spawnable service agents from the registry
  /switch <agent_id>          Switch current target
  /echo <text|md|void>        Select the echo renderer for incoming replies
                              (text = plain, md = markdown, void = discard)
  /status [agent_id]          Show FSM state & strategy
  /skills [agent] [skills…]   Show or set agent skills
  /scope list                 List domain scope definitions
  /scope show <id>            Show a domain scope document
  /providers                  List available LLM providers
  /models <provider>          List models for a provider
  /models pull <model>        Pull an Ollama model from the registry
  /models ps [host]           Show models currently loaded in Ollama memory
  /attach <path>              Upload a file as an artifact
  /artifact list              List platform artifacts
  /artifact get <id>          Download / inspect an artifact
  /artifact send <agent> <id> Send an artifact to an agent
  /federation                 Show federation status
  /join <room> [agents…]      Join (or create) a group room; optionally add agents
  /part [room]               Leave a group room (defaults to current room)
  /list                      List all active group rooms and their members
  /permissions               List pending code execution permission requests
  /approve [request_id]      Approve a pending code execution request
  /deny [request_id]         Deny a pending code execution request
  /help                       This help text
  /quit  or  Ctrl-D           Quit

Any other text is sent as a message to the current agent (fire-and-forget).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import Any

from mars.cli.models import (
    HUMAN_AVATARS,
    AGENT_EMOJIS,
    EVENT_ICONS,
    _AGENT_ROLE,
    ChatMessage,
    AgentRecord,
    FeedItem,
    DEFAULT_PORT,
    DEFAULT_FEDERATION_PORT,
    MARSState,
    _SIDEBAR_PINNED,
    _CONVERSATIONAL_TYPES,
    _is_conversational,
    _sidebar_agent_ids,
    _nav_sidebar,
    _sync_sidebar_cursor,
)
from mars.cli.utils import (
    _local_ip,
    _time_ago,
    _normalize_agent_type,
    _running_service_agent_names,
    _load_dotenv,
)
from mars.cli.service_manager import (
    _emit_spawn_status,
    _launch_service_agent,
    _stop_service_agents,
    _stop_service_agents_async,
    _auto_spawn_free_agents,
)
from mars.cli.renderer import MARSRenderer
from mars.cli.client import MARSClientTerminal


def main(argv: list[str] | None = None) -> None:
    _load_dotenv()  # pick up .env before parsing args
    parser = argparse.ArgumentParser(
        prog="mars",
        description="MARS – Multi-Agent Runtime System interactive terminal",
    )
    parser.add_argument("--provider", "-p", nargs="+", default=None,
                        help="LLM provider(s) for initial agents, e.g. --provider github-models ollama")
    parser.add_argument("--model",    "-m", default=None,
                        help="Model name for the provider")
    parser.add_argument("--name",     "-n", default=None,
                        help="Agent ID for the initial agent")
    parser.add_argument("--key",      "-k", default=None,
                        help="API key (overrides environment variable)")
    parser.add_argument("--connect", "-c", nargs="*", default=None,
                        metavar="HOST[:PORT]",
                        help=(f"Federate with one or more MARS nodes "
                              f"(default federation port: {DEFAULT_FEDERATION_PORT})"))
    parser.add_argument("--remote", "-r", default=None,
                        metavar="HOST[:PORT]",
                        help=(f"Connect to a running mars-server as a thin TUI client "
                              f"(TCP bus port, default: 127.0.0.1:{DEFAULT_PORT})"))
    parser.add_argument("--debug", action="store_true",
                        help="Enable DEBUG logging")
    args = parser.parse_args(argv)

    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    if args.remote:
        # Thin TCP client mode — connect directly to the MARS bus (port 7432)
        args.connect = args.remote
        asyncio.run(_async_client(args))
    else:
        connect_addrs: list[str] = args.connect if args.connect else []
        asyncio.run(_async_main(args, connect_addrs=connect_addrs))


async def _async_client(args: argparse.Namespace, *, _preconnected: tuple | None = None) -> None:
    """Connect to a running mars-server as a thin TUI client.

    Uses the same hello-first protocol as service agents and LLM agents:
      1. Connect
      2. Send hello (with role="human")
      3. Server responds with welcome + agent roster
      4. Run TUI — all further events arrive via _receive_events

    If *_preconnected* is supplied (a ``(reader, writer)`` pair already open),
    the connection step is skipped and the existing stream is used directly.
    """
    connect_arg = args.connect[0] if isinstance(args.connect, list) and args.connect else args.connect
    connect_str = connect_arg or "localhost"
    if connect_str.startswith(":"):
        host, port = "localhost", int(connect_str[1:])
    elif ":" in connect_str:
        host, port_str = connect_str.rsplit(":", 1)
        host = host or "localhost"
        port = int(port_str)
    else:
        host, port = connect_str, DEFAULT_PORT

    if _preconnected is not None:
        reader, writer = _preconnected
    else:
        print(f"🔌 Connecting to MARS server at {host}:{port} …")
        try:
            reader, writer = await asyncio.open_connection(host, port, limit=16 * 1024 * 1024)
        except ConnectionRefusedError:
            print(f"❌ Cannot connect to {host}:{port}", file=sys.stderr)
            print(f"   Start the server first:  mars-server [--provider <provider>]", file=sys.stderr)
            sys.exit(1)
        except OSError as exc:
            print(f"❌ Connection error: {exc}", file=sys.stderr)
            sys.exit(1)

    state = MARSState()
    server_addr = f"{host}:{port}"
    terminal = MARSClientTerminal(reader, writer, state, server_addr=server_addr)

    # Send hello immediately — same as every other client type.
    hello_payload: dict[str, Any] = {"t": "hello", "role": "human", "name": "cli-user"}
    writer.write((json.dumps(hello_payload) + "\n").encode())
    await writer.drain()

    # Apply the first real event (welcome or spawn) then hand off to TUI.
    first_line = await reader.readline()
    try:
        first_msg = json.loads(first_line.decode("utf-8"))
    except Exception:
        first_msg = {}
    terminal._apply_event(first_msg)
    try:
        await terminal.run()
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _async_main(args: argparse.Namespace, connect_addrs: list[str] = []) -> None:
    """Start a local MARS server subprocess and connect to it via TCP.

    Both standalone and --remote modes use the same TCP client path, which
    eliminates any split-brain between in-process state and TCP service agents.

    The readiness-probe connection is *reused* as the actual client session —
    only one TCP connection is ever established.
    """
    import subprocess as _subprocess

    server_host = "127.0.0.1"
    server_port = DEFAULT_PORT

    # Forward relevant args to the server subprocess
    cmd = [sys.executable, "-m", "mars.srv.main",
           "--host", server_host, "--port", str(server_port)]
    if getattr(args, "provider", None):
        for p in args.provider:
            cmd += ["--provider", p]
    if getattr(args, "model", None):
        cmd += ["--model", args.model]
    if getattr(args, "key", None):
        cmd += ["--key", args.key]
    if getattr(args, "debug", False):
        cmd += ["--debug"]
    for ca in connect_addrs:
        cmd += ["--connect", ca]

    proc = _subprocess.Popen(cmd)

    # Poll until the server accepts connections (up to 15 s).
    # The first successful connection IS the real client session — we keep it
    # open and pass it directly to _async_client so no second handshake occurs.
    reader = writer = None
    for _ in range(30):
        try:
            reader, writer = await asyncio.open_connection(
                server_host, server_port, limit=16 * 1024 * 1024
            )
            break
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.5)

    if reader is None:
        print("❌  Local MARS server failed to start within 15 s", file=sys.stderr)
        proc.terminate()
        return

    # Connect as a thin TCP client — identical to --remote mode.
    args.connect = f"{server_host}:{server_port}"
    try:
        await _async_client(args, _preconnected=(reader, writer))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except _subprocess.TimeoutExpired:
            proc.kill()




__all__ = [
    "main", "datetime",
    "HUMAN_AVATARS", "AGENT_EMOJIS", "EVENT_ICONS", "_AGENT_ROLE",
    "ChatMessage", "AgentRecord", "FeedItem",
    "DEFAULT_PORT", "DEFAULT_FEDERATION_PORT", "MARSState",
    "_SIDEBAR_PINNED", "_CONVERSATIONAL_TYPES", "_is_conversational",
    "_sidebar_agent_ids", "_nav_sidebar", "_sync_sidebar_cursor",
    "_local_ip", "_time_ago", "_normalize_agent_type",
    "_running_service_agent_names", "_load_dotenv",
    "_emit_spawn_status", "_launch_service_agent", "_stop_service_agents",
    "_stop_service_agents_async", "_auto_spawn_free_agents",
    "MARSRenderer", "MARSClientTerminal",
    "_async_client", "_async_main",
]

if __name__ == "__main__":
    main()
