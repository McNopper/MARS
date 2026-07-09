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
  • Replies appear directly in the chat panel; the dot turns green when the agent is idle again.
  • Multiple agents can be THINKING simultaneously.

Agent type icons (sidebar & tiles)
-----------------------------------
  🤖  LLMAgent        📡  SensorAgent      🖥️  CLIBridgeAgent
  🔧  Provider       🌉  BridgeAgent      👤  Generic Agent    📢  Verbose (auto-print)
  👽  Suspicious      👾  Blocked

Sidebar status dot  ●
----------------------
  🟢 green   IDLE — agent is ready to receive a message
  🔵 blue    THINKING — agent is actively processing (working)
  🔴 red     ERROR — agent crashed, failed, or is blocked
  ⚫ grey    Other state (spawning, despawning …)

Tile border colours (full TUI mode)
------------------------------------
  green   Ready to receive (IDLE)    blue    Thinking (working)
  red     Error / crashed            grey    Other state

Commands
--------
Agents
  /spawn <provider> [model]   Spawn a new LLM agent (ollama, copilot, mock, …)
                              Options: --name NAME --role ROLE --goal GOAL
                                       --behaviour reactive|proactive
                                       --key KEY --host HOST
  /spawn <service>            Spawn a built-in service agent (profiler, status, shell, …)
  /stop <agent_id>            Stop and despawn an agent
  /agents                     List active agents
  /agents available           List all spawnable agents from the registry
  /switch <agent_id>          Switch current target (also: sidebar ↑/↓ keys)
  /status [agent_id]          Show FSM state & strategy
  /verbose [agent_id]         Toggle auto-print replies for an agent
  /avatar [n|emoji]           Pick your human avatar

Rooms
  /join <room> [agents…]      Join (or create) a group room; optionally add agents
  /part [room]                Leave a group room (defaults to current room)
  /list                       List all active group rooms and their members

Conversation
  /new                        Clear local conversation history
  /compact                    Summarise and compress conversation history
  /rewind                     Remove last user + agent message pair
  /ask <question>             Ephemeral side question (not stored in history)
  /plan <task>                Ask agent for a step-by-step implementation plan
  /read [agent_id]            Read pending reply (default: current agent)

Workspace
  @path                       Expand file contents inline before sending
  !cmd                        Run a local shell command; show output in reply panel
  /copy                       Copy last reply to clipboard
  /context                    Show token usage estimate for current context
  /instructions               Load AGENTS.md / CLAUDE.md / copilot-instructions.md
  /share [filename]           Export conversation to a Markdown file
  /search <query>             Search conversation history

Rendering
  /echo <text|md|void>        Select the echo renderer (text = plain, md = markdown, void = discard)
  /theme [name]               Switch color theme (dark, light, dracula, solarized)

Other
  /version                    Show installed MARS version
  /help                       This help text
  /quit  or  Ctrl-D           Quit

Any other text is sent as a message to the current agent (fire-and-forget).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import subprocess
import sys
from datetime import datetime
from typing import Any

from mars.cli.client import MARSClientTerminal
from mars.common.wire import decode_frame, encode_frame
from mars.cli.commands import (  # noqa: F401 — re-exported for backward compatibility
    _cmd_ask,
    _cmd_compact,
    _cmd_context,
    _cmd_copy,
    _cmd_instructions,
    _cmd_new,
    _cmd_plan,
    _cmd_rewind,
    _cmd_search,
    _cmd_share,
    _cmd_version,
    _expand_file_mentions,
    _handle_bang_cmd,
)
from mars.common.models import (
    _AGENT_ROLE,
    AGENT_EMOJIS,
    DEFAULT_FEDERATION_PORT,
    DEFAULT_PORT,
    EVENT_ICONS,
    HUMAN_AVATARS,
    AgentRecord,
    ChatMessage,
    FeedItem,
    MARSState,
)
from mars.cli.nav import (
    _CONVERSATIONAL_TYPES,
    _is_conversational,
    _nav_connections,
    _sidebar_agent_ids,
    _sync_sidebar_cursor,
)
from mars.cli.renderer import MARSRenderer
from mars.server.service_manager import (
    _auto_spawn_free_providers,
    _emit_spawn_status,
    _launch_provider,
    _stop_providers,
    _stop_providers_async,
)
from mars.cli.utils import (
    _load_dotenv,
    _local_ip,
    _normalize_agent_type,
    _running_provider_names,
    _time_ago,
)


def main(argv: list[str] | None = None) -> None:
    _load_dotenv()  # pick up .env before parsing args
    parser = argparse.ArgumentParser(
        prog="mars",
        description="MARS – Multi-Agent Runtime System interactive terminal",
    )
    parser.add_argument("--provider", "-p", nargs="+", default=None,
                        help="LLM service(s) for initial agents (e.g. --provider ollama copilot)")
    parser.add_argument("--model",    "-m", default=None,
                        help="Model name for the service")
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
                        help=(f"Connect to a running MARS server as a thin TUI client "
                              f"(TCP bus port, default: 127.0.0.1:{DEFAULT_PORT})"))
    parser.add_argument("--debug", action="store_true",
                        help="Enable DEBUG logging")
    args = parser.parse_args(argv)

    if args.debug:
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
        print(f"[*] Connecting to MARS server at {host}:{port} ...")
        try:
            reader, writer = await asyncio.open_connection(host, port, limit=16 * 1024 * 1024)
        except ConnectionRefusedError:
            print(f"[ERROR] Cannot connect to {host}:{port}", file=sys.stderr)
            print("   Start the server first:  python -m mars.server.main [--provider <provider>]", file=sys.stderr)
            sys.exit(1)
        except OSError as exc:
            print(f"❌ Connection error: {exc}", file=sys.stderr)
            sys.exit(1)

    state = MARSState()
    server_addr = f"{host}:{port}"
    terminal = MARSClientTerminal(reader, writer, state, server_addr=server_addr)

    # Send hello immediately — same as every other client type.
    hello_payload: dict[str, Any] = {"t": "hello", "role": "human", "name": "cli-user"}
    writer.write(encode_frame(hello_payload))
    await writer.drain()

    # Apply the first real event (welcome or spawn) then hand off to TUI.
    first_line = await reader.readline()
    first_msg = decode_frame(first_line) or {}
    terminal._apply_event(first_msg)
    try:
        await terminal.run()
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def _async_main(args: argparse.Namespace, connect_addrs: list[str] = None) -> None:
    """Start a local MARS server subprocess and connect to it via TCP.

    Both standalone and --remote modes use the same TCP client path, which
    eliminates any split-brain between in-process state and TCP service agents.

    The readiness-probe connection is *reused* as the actual client session —
    only one TCP connection is ever established.
    """
    if connect_addrs is None:
        connect_addrs = []
    server_host = "127.0.0.1"
    server_port = DEFAULT_PORT

    # Forward relevant args to the server subprocess
    cmd = [sys.executable, "-m", "mars.server.main",
           "--host", server_host, "--port", str(server_port)]
    if getattr(args, "provider", None):
        cmd += ["--provider"] + list(args.provider)
    if getattr(args, "model", None):
        cmd += ["--model", args.model]
    if getattr(args, "key", None):
        cmd += ["--key", args.key]
    if getattr(args, "debug", False):
        cmd += ["--debug"]
    for ca in connect_addrs:
        cmd += ["--connect", ca]

    proc = subprocess.Popen(cmd)

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
        except subprocess.TimeoutExpired:
            proc.kill()




__all__ = [
    "main", "datetime",
    "HUMAN_AVATARS", "AGENT_EMOJIS", "EVENT_ICONS", "_AGENT_ROLE",
    "ChatMessage", "AgentRecord", "FeedItem",
    "DEFAULT_PORT", "DEFAULT_FEDERATION_PORT", "MARSState",
    "_CONVERSATIONAL_TYPES", "_is_conversational",
    "_sidebar_agent_ids", "_nav_connections", "_sync_sidebar_cursor",
    "_local_ip", "_time_ago", "_normalize_agent_type",
    "_running_provider_names", "_load_dotenv",
    "_emit_spawn_status", "_launch_provider", "_stop_providers",
    "_stop_providers_async", "_auto_spawn_free_providers",
    "MARSRenderer", "MARSClientTerminal",
    "_async_client", "_async_main",
]

if __name__ == "__main__":
    main()



