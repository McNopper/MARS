"""System tests: Filesystem MCP server integration.

Two test classes:

  TestFakeFilesystemMCPServer
    Offline — uses an embedded fake filesystem MCP server to verify the full
    MARS integration: registration, tool schema propagation, tool call
    round-trips (write_file, read_file, edit_file).
    Runs on every CI pass (no npx/Node required).

  TestRealFilesystemMCPServer
    Requires npx (Node.js 18+) on PATH.
    Skipped automatically when npx is missing.
    Exercises: server start, tool discovery, write/read/edit round-trips.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import tempfile

import pytest

import tests.system.helpers as helpers
from mars.constants import CATEGORY_EXTERNAL, COST_DEMAND, PROTOCOL_MCP
from mars.runtime.services.registry import AgentSpec

# ---------------------------------------------------------------------------
# Inline fake filesystem MCP server (in-memory, no real disk I/O)
# ---------------------------------------------------------------------------

_FAKE_FILESYSTEM_MCP = r"""
import json, sys

_files = {}  # in-memory virtual filesystem

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Edit a file with diff-based edits",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":   {"type": "string"},
                "edits":  {"type": "array"},
                "dryRun": {"type": "boolean"},
            },
            "required": ["path", "edits"],
        },
    },
    {
        "name": "list_directory",
        "description": "List directory entries",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "create_directory",
        "description": "Create a directory",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search files by pattern",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "pattern": {"type": "string"},
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "move_file",
        "description": "Move or rename a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source":      {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["source", "destination"],
        },
    },
    {
        "name": "get_file_info",
        "description": "Get metadata for a file",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_multiple_files",
        "description": "Read multiple files at once",
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array"}},
            "required": ["paths"],
        },
    },
    {
        "name": "list_allowed_directories",
        "description": "List allowed directories",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def send(msg):
    sys.stdout.buffer.write((json.dumps(msg) + "\n").encode())
    sys.stdout.buffer.flush()


for raw in sys.stdin:
    raw = raw.strip()
    if not raw:
        continue
    try:
        req = json.loads(raw)
    except Exception:
        continue
    rid  = req.get("id")
    meth = req.get("method", "")
    if meth == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-filesystem", "version": "0.1"},
        }})
    elif meth == "notifications/initialized":
        pass
    elif meth == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif meth == "tools/call":
        params = req.get("params", {})
        name   = params.get("name", "")
        args   = params.get("arguments", {})
        is_error = False
        try:
            if name == "write_file":
                _files[args["path"]] = args["content"]
                text = json.dumps({"ok": True, "path": args["path"]})
            elif name == "read_file":
                content = _files.get(args["path"])
                if content is None:
                    text = json.dumps({"error": f"File not found: {args['path']}"})
                    is_error = True
                else:
                    text = content
            elif name == "edit_file":
                path     = args["path"]
                edits    = args.get("edits", [])
                dry_run  = args.get("dryRun", False)
                current  = _files.get(path, "")
                for edit in edits:
                    current = current.replace(edit["oldText"], edit["newText"])
                if not dry_run:
                    _files[path] = current
                text = current
            elif name == "list_directory":
                prefix  = args["path"].rstrip("/") + "/"
                entries = [k for k in _files if k.startswith(prefix)]
                text    = json.dumps({"entries": entries})
            elif name == "create_directory":
                text = json.dumps({"ok": True})
            elif name == "search_files":
                pattern = args.get("pattern", "")
                matches = [k for k in _files if pattern in k]
                text    = json.dumps({"matches": matches})
            elif name == "move_file":
                src, dst = args["source"], args["destination"]
                if src in _files:
                    _files[dst] = _files.pop(src)
                    text = json.dumps({"ok": True})
                else:
                    text    = json.dumps({"error": f"File not found: {src}"})
                    is_error = True
            elif name == "get_file_info":
                path = args["path"]
                if path in _files:
                    text = json.dumps({"path": path, "size": len(_files[path]), "type": "file"})
                else:
                    text    = json.dumps({"error": f"Not found: {path}"})
                    is_error = True
            elif name == "read_multiple_files":
                results = {p: _files.get(p, f"(not found: {p})") for p in args.get("paths", [])}
                text    = json.dumps(results)
            elif name == "list_allowed_directories":
                text = json.dumps({"directories": ["."]})
            else:
                text     = json.dumps({"error": f"Unknown tool: {name}"})
                is_error = True
        except Exception as exc:
            text     = json.dumps({"error": str(exc)})
            is_error = True
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown"}})
"""


def _python_inline_cmd(code: str) -> str:
    encoded = base64.b64encode(code.encode()).decode()
    exe = sys.executable.replace("\\", "/")
    return f'"{exe}" -c "import base64,sys; exec(base64.b64decode(b\'{encoded}\').decode())"'


def _fake_filesystem_spec() -> AgentSpec:
    return AgentSpec(
        name="filesystem",
        description="Fake filesystem MCP server for testing",
        command=_python_inline_cmd(_FAKE_FILESYSTEM_MCP),
        skills=["read_file", "write_file", "edit_file", "read_multiple_files",
                "list_directory", "move_file", "search_files", "get_file_info",
                "create_directory", "list_allowed_directories"],
        category=CATEGORY_EXTERNAL,
        cost=COST_DEMAND,
        protocol=PROTOCOL_MCP,
    )


# ---------------------------------------------------------------------------
# Offline tests (fake binary — no npx required)
# ---------------------------------------------------------------------------

class TestFakeFilesystemMCPServer:
    """Full integration using the embedded fake filesystem MCP server."""

    async def test_filesystem_server_registers_tools(self, unused_tcp_port):
        """Fake filesystem MCP server spawns and registers all 10 tools."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_filesystem_spec()), timeout=10.0)

        agent_ids = list(server._mcp_adapters.keys())
        assert len(agent_ids) == 1, f"Expected 1 MCP agent, got {len(agent_ids)}"

        tools = server._mcp_adapters[agent_ids[0]].tools
        names = {t.name for t in tools}
        for expected in ("read_file", "write_file", "edit_file", "list_directory",
                         "move_file", "search_files", "get_file_info",
                         "read_multiple_files", "list_allowed_directories"):
            assert expected in names, f"{expected} missing from tools: {names}"

        await server.stop_mcp_agents()

    async def test_tool_schemas_in_spawn_event(self, unused_tcp_port):
        """spawn event for filesystem MCP carries full tool schemas."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_filesystem_spec()), timeout=10.0)

        h_reader, h_writer = await helpers.connect(unused_tcp_port, "cli-user")
        initial = await helpers.read_initial_events(h_reader)

        fs_spawns = [e for e in initial if e.get("t") == "spawn"
                     and "filesystem" in e.get("agent_id", "")]
        assert fs_spawns, "No filesystem spawn event in initial events"

        schemas = {s["name"]: s for s in fs_spawns[0].get("tool_schemas", [])}
        assert "edit_file" in schemas, f"edit_file missing; got: {list(schemas)}"
        props = schemas["edit_file"].get("input_schema", {}).get("properties", {})
        assert "path" in props and "edits" in props

        h_writer.close()
        await server.stop_mcp_agents()

    async def test_write_then_read_file_round_trip(self, unused_tcp_port):
        """write_file followed by read_file returns the written content."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_filesystem_spec()), timeout=10.0)
        agent_id = next(iter(server._mcp_adapters))

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        # Write a file
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "write_file",
            "__args__": {"path": "hello.txt", "content": "Hello, MARS!"},
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=10.0)
        result = json.loads(ev["text"])
        assert result.get("ok") is True

        # Read it back
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "read_file",
            "__args__": {"path": "hello.txt"},
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=10.0)
        assert ev["text"] == "Hello, MARS!"

        writer.close()
        await server.stop_mcp_agents()

    async def test_edit_file_applies_diff_based_changes(self, unused_tcp_port):
        """edit_file replaces oldText with newText in the target file."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_filesystem_spec()), timeout=10.0)
        agent_id = next(iter(server._mcp_adapters))

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        # Seed the file
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "write_file",
            "__args__": {"path": "greeting.txt", "content": "Hello, World!"},
        }))
        await writer.drain()
        await helpers.read_until(reader, t="msg", timeout=10.0)

        # Apply a diff edit
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "edit_file",
            "__args__": {
                "path":  "greeting.txt",
                "edits": [{"oldText": "World", "newText": "MARS"}],
            },
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=10.0)
        assert ev["text"] == "Hello, MARS!"

        writer.close()
        await server.stop_mcp_agents()

    async def test_edit_file_dry_run_does_not_persist(self, unused_tcp_port):
        """edit_file with dryRun=True returns changed content but does not save."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_filesystem_spec()), timeout=10.0)
        agent_id = next(iter(server._mcp_adapters))

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        # Seed the file
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "write_file",
            "__args__": {"path": "stable.txt", "content": "original content"},
        }))
        await writer.drain()
        await helpers.read_until(reader, t="msg", timeout=10.0)

        # Dry-run edit — must NOT persist
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "edit_file",
            "__args__": {
                "path":   "stable.txt",
                "edits":  [{"oldText": "original", "newText": "modified"}],
                "dryRun": True,
            },
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=10.0)
        assert "modified" in ev["text"], "dry-run should preview the modified content"

        # Now read back the real file — should still have original content
        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "read_file",
            "__args__": {"path": "stable.txt"},
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=10.0)
        assert ev["text"] == "original content", "file should be unchanged after dryRun"

        writer.close()
        await server.stop_mcp_agents()

    async def test_read_multiple_files(self, unused_tcp_port):
        """read_multiple_files returns a dict of path→content."""
        server = await helpers.start_server(unused_tcp_port)
        await asyncio.wait_for(server._spawn_mcp_agent(_fake_filesystem_spec()), timeout=10.0)
        agent_id = next(iter(server._mcp_adapters))

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        for fname, content in [("a.txt", "Alpha"), ("b.txt", "Beta")]:
            helpers.send_msg(writer, agent_id, json.dumps({
                "__tool__": "write_file",
                "__args__": {"path": fname, "content": content},
            }))
            await writer.drain()
            await helpers.read_until(reader, t="msg", timeout=10.0)

        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "read_multiple_files",
            "__args__": {"paths": ["a.txt", "b.txt"]},
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=10.0)
        result = json.loads(ev["text"])
        assert result["a.txt"] == "Alpha"
        assert result["b.txt"] == "Beta"

        writer.close()
        await server.stop_mcp_agents()


# ---------------------------------------------------------------------------
# Real filesystem MCP server tests (skipped when npx is unavailable)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not helpers.npx_available(),
    reason="npx not found on PATH — install Node.js 18+ to run filesystem MCP tests",
)
class TestRealFilesystemMCPServer:
    """Tests using the real @modelcontextprotocol/server-filesystem via npx."""

    def _real_spec(self, allowed_dir: str) -> AgentSpec:
        return AgentSpec(
            name="filesystem",
            description="Real filesystem MCP server",
            command=f"npx -y @modelcontextprotocol/server-filesystem {allowed_dir}",
            skills=["read_file", "write_file", "edit_file"],
            category=CATEGORY_EXTERNAL,
            cost=COST_DEMAND,
            protocol=PROTOCOL_MCP,
        )

    async def test_real_server_registers_tools(self, unused_tcp_port, tmp_path):
        """Real filesystem MCP server starts and advertises its tools."""
        server = await helpers.start_server(unused_tcp_port)
        spec = self._real_spec(str(tmp_path))
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=30.0)

        agent_ids = [aid for aid in server._mcp_adapters if "filesystem" in aid]
        assert agent_ids, "No filesystem MCP adapter registered"

        tools = server._mcp_adapters[agent_ids[0]].tools
        tool_names = {t.name for t in tools}
        for expected in ("read_file", "write_file", "edit_file"):
            assert expected in tool_names, f"{expected} missing; got: {tool_names}"

        await server.stop_mcp_agents()

    async def test_real_write_and_read_file(self, unused_tcp_port, tmp_path):
        """Real filesystem MCP server can write and read a file on disk."""
        server = await helpers.start_server(unused_tcp_port)
        spec = self._real_spec(str(tmp_path))
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=30.0)
        agent_id = next(aid for aid in server._mcp_adapters if "filesystem" in aid)

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        test_file = str(tmp_path / "mars_test.txt")

        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "write_file",
            "__args__": {"path": test_file, "content": "Hello from MARS tests!"},
        }))
        await writer.drain()
        # wait for confirmation
        await helpers.read_until(reader, t="msg", timeout=15.0)

        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "read_file",
            "__args__": {"path": test_file},
        }))
        await writer.drain()
        ev = await helpers.read_until(reader, t="msg", timeout=15.0)
        assert "Hello from MARS tests!" in ev["text"]

        writer.close()
        await server.stop_mcp_agents()

    async def test_real_edit_file(self, unused_tcp_port, tmp_path):
        """Real filesystem MCP server can apply diff-based edits."""
        server = await helpers.start_server(unused_tcp_port)
        spec = self._real_spec(str(tmp_path))
        await asyncio.wait_for(server._spawn_mcp_agent(spec), timeout=30.0)
        agent_id = next(aid for aid in server._mcp_adapters if "filesystem" in aid)

        reader, writer = await helpers.connect(unused_tcp_port, "llm-agent", role="agent")
        await helpers.read_until(reader, t="welcome")

        test_file = str(tmp_path / "edit_test.txt")
        # Write initial content directly to disk (bypass MCP for speed)
        (tmp_path / "edit_test.txt").write_text("version: 1.0\nstatus: draft")

        helpers.send_msg(writer, agent_id, json.dumps({
            "__tool__": "edit_file",
            "__args__": {
                "path":  test_file,
                "edits": [{"oldText": "draft", "newText": "final"}],
            },
        }))
        await writer.drain()
        await helpers.read_until(reader, t="msg", timeout=15.0)

        # Verify on disk
        content = (tmp_path / "edit_test.txt").read_text()
        assert "final" in content
        assert "draft" not in content

        writer.close()
        await server.stop_mcp_agents()
