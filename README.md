# 🌌 MARS — Multi-Agent Runtime System

MARS is a **minimal, standards-aligned runtime** where humans and heterogeneous AI agents share one live message bus, discover each other's skills, and collaborate using standardized protocols.

## 🚀 Standard Protocols

MARS implements industry-standard protocols for all communication:

### 🔗 Protocol Standards Used

- **[AG-UI Protocol](https://github.com/ag-ui-protocol/ag-ui)** - Human CLI to agent server communication
- **[A2A Protocol](https://github.com/a2aproject/A2A)** - Agent-to-agent communication  
- **[MCP (Model Context Protocol)](https://modelcontextprotocol.io/)** - Service agent and tool communication
- **MARS Federation Protocol** - MARS-MARS federation (proprietary, based on Protocol Buffers)

### 📡 Protocol Architecture

```
┌─────────────────────────────────────────────────────┐
│                   MARS Protocol Stack                  │
├─────────────────────────────────────────────────────┤
│  Human-CLI          │  AG-UI Protocol                 │
│  Agent-Agent        │  A2A Protocol (JSON-RPC 2.0)    │
│  Service-Agent      │  MCP Protocol (stdio)           │
│  MARS-MARS          │  MARS Protocol (Protobuf)        │
├─────────────────────────────────────────────────────┤
│  Wire Layer         │  Multi-protocol framing         │
│  Protocol Adapters  │  Unified adapter interface      │
└─────────────────────────────────────────────────────┘
```

### 🔗 Standard Specifications

- **[AG-UI Specification](https://github.com/ag-ui-protocol/ag-ui)** - Event-based agent-human interaction
- **[A2A Specification](https://a2a-protocol.org/v0.3.0/specification/)** - Agent interoperability protocol
- **[MCP Specification](https://modelcontextprotocol.io/docs/getting-started/intro)** - Model Context Protocol for tools
- **[MCP SDK](https://github.com/modelcontextprotocol/python-sdk)** - Python SDK implementation

## The Unified Architecture Concept

**Everything is a Service.**

MARS unifies all capabilities — LLMs, tools, data sources, connections — as **Services** with a consistent interface. Each service exposes its capabilities as tools that can be dynamically discovered and used by LLMs.

## Bootstrapping LLMs with Discovery

**Key insight:** LLMs don't need to know all services upfront. They only need to know about the **Discovery Service** (communicated via MCP).

1. **Initial Bootstrap**: LLM is told only about the Discovery Service
2. **Dynamic Discovery**: LLM queries Discovery Service for available tools via MCP
3. **Runtime Updates**: Services can appear/disappear during runtime
4. **Tool Execution**: LLM calls discovered service tools through MCP protocol

```
LLM → "What tools exist?"
LLM → Discovery Service.discover_all_capabilities() [via MCP]
Discovery Service → queries all registered services dynamically
Discovery Service → returns complete tool list
LLM → executes tools via MCP tool calls
```

## Quick Start

Requires Python 3.14+.

### Start the server

```bash
# Bare server (no LLM agents pre-spawned)
python -m mars.server.main

# Pre-spawn an Ollama agent on startup
python -m mars.server.main --provider ollama

# Pre-spawn with a specific model
python -m mars.server.main --provider ollama --model qwen3:4b

# Enable full protocol logging to the audit file (useful for debugging)
python -m mars.server.main --audit-verbose

# Custom ports
python -m mars.server.main --port 7432 --http-port 7433 --ws-port 7434
```

### Start the TUI client

```bash
# Launch client + embedded server together (default)
python -m mars.cli.main

# Pre-spawn an LLM agent directly from the CLI
python -m mars.cli.main --provider ollama
python -m mars.cli.main --provider ollama --model qwen3:4b

# Connect to an already-running server (thin client mode)
python -m mars.cli.main --remote 127.0.0.1:7432
```

### Typical two-terminal workflow

```bash
# Terminal 1 — server
python -m mars.server.main --provider ollama

# Terminal 2 — TUI
python -m mars.cli.main --remote 127.0.0.1:7432
```

## Available Services

All services communicate via **MCP protocol** (Model Context Protocol).

**LLM Services** (🤖)
- `anthropic` — Anthropic Claude (alias: `claude`)
- `copilot` — GitHub Copilot Chat
- `ollama` — Local Ollama server
- `mock` / `mock-tool` — test-only providers, hidden from normal discovery

**MCP Services** (⚙️)
- `discovery` — **Primary bootstrap service** (starts automatically)
- `status` — Core status service
- `launcher` — Agent launcher service
- `filesystem` — MCP filesystem server (stdio)
- `mcp-generic` — Generic MCP server adapter

**A2A Services** (🌐)
- `remote-mars` — A2A peer connection to remote MARS instances

**Federation Services** (🌍)
- MARS-MARS federation for cross-node agent sharing

## Protocol Features

### AG-UI Protocol (Human-CLI)
- Event-based human-agent interaction
- Streaming responses
- Artifact generation
- State synchronization

### A2A Protocol (Agent-Agent)
- JSON-RPC 2.0 messaging
- Task lifecycle management
- Agent Card discovery
- Cross-system federation

### MCP Protocol (Services)
- Tool discovery and invocation
- Resource access
- Prompt templates
- Stdio server communication

### MARS Federation Protocol
- Node handshaking
- Agent lifecycle synchronization
- Federated messaging
- Artifact transfer
- Health monitoring

## Discovery Service Tools

The Discovery Service exposes these tools to LLMs:

- **`list_services`** — List all available services currently registered
- **`get_service_info`** — Get detailed info about a specific service
- **`discover_all_capabilities`** — Discover all tools/capabilities from all services
- **`discover_service_capabilities`** — Get capabilities from a specific service

## Dynamic Service Discovery

**Example workflow:**

```bash
# 1. LLM starts with only Discovery Service awareness
LLM → "What services are available?"

# 2. Discovery Service queries all services dynamically
Discovery Service → Returns the currently available services and capabilities

# 3. LLM receives tool list
LLM → Can now use tools from any service
LLM → Executes: filesystem_service.call_tool("read_file", path="README.md")
```

**Services can appear/disappear during runtime** — the Discovery Service provides real-time discovery of what's currently available.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MARS SERVICES                             │
│  (All tool providers, data sources, and capabilities)         │
└─────────────────────────────────────────────────────────────┘

Types of Services:
┌───────────────────────────────────────────────────────────────┐
│ 1. LLM Services (🤖) — Anthropic, Ollama, Copilot                │
│ 2. MCP Services (⚙️) — Filesystem, databases, custom tools    │  
│ 3. A2A Services (🌐) — Remote MARS instances, federation        │
│ 4. Builtin Services (🔧) — Discovery, Status, Launcher, etc.   │
└───────────────────────────────────────────────────────────────┘
```

Each service implements the **Service interface** with:
- `service_id` — Unique identifier
- `service_type` — Type category (llm, mcp, a2a, builtin)
- `capabilities` — List of tools/capabilities the service provides
- `call_tool(tool_name, **kwargs)` — Execute a capability
- `initialize()` / `shutdown()` — Lifecycle management

Test-only mock providers are kept for the test suite, but they are hidden from the normal services panel and discovery output.