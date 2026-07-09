# 🌌 MARS — Multi-Agent Runtime System

MARS is a **minimal, standards-aligned multi-agent runtime** where humans and AI agents share one live message bus, discover each other's capabilities, and collaborate through open protocols.

## Core Design Principle

**Everything is a service.** Tools, LLMs, data sources, connections — all exposed as services with a consistent interface. Agents discover capabilities at runtime through the Discovery Service rather than being hard-wired to specific tools.

## Protocol Stack

MARS implements three open standards, each with a distinct responsibility:

| Layer | Protocol | Purpose |
|-------|----------|---------|
| Human ↔ Client | [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | Event-based human-agent interaction |
| Agent ↔ Agent | [A2A](https://google.github.io/A2A/) | Agent interoperability and task delegation |
| Agent ↔ Tools | [MCP](https://modelcontextprotocol.io/) | Service discovery and tool invocation |
| MARS ↔ MARS | Custom | Node federation — no open standard exists yet |

```mermaid
graph TB
    Human["👤 Human"]
    TUI["TUI / Frontend"]
    Server["MARS Server"]
    LLM["🤖 LLM Agent"]
    Svc["⚙️ Service / Tool"]
    Peer["🌍 Remote MARS Node"]

    Human -->|AG-UI| TUI
    TUI -->|AG-UI| Server
    LLM -->|A2A| Server
    Server -->|A2A| LLM
    Server -->|MCP| Svc
    Svc -->|MCP| Server
    Server <-->|Custom federation| Peer
```

### AG-UI — Human ↔ Client

> Spec: <https://github.com/ag-ui-protocol/ag-ui>  
> Docs: <https://docs.ag-ui.com/>

AG-UI is an open, lightweight, event-based protocol that standardises how AI agents connect to user-facing applications. MARS uses it for the channel between the human operator and the server so that any AG-UI-compatible frontend can connect.

### A2A — Agent ↔ Agent

> Spec: <https://google.github.io/A2A/>  
> SDK: <https://github.com/google/A2A>

A2A (Agent-to-Agent) is Google's open protocol for agent interoperability. It defines JSON-RPC 2.0 messaging, task lifecycle management, and Agent Cards for discovery. MARS uses A2A for all agent-to-agent communication.

### MCP — Agent ↔ Tools / Services

> Spec: <https://modelcontextprotocol.io/specification>  
> Python SDK: <https://github.com/modelcontextprotocol/python-sdk>

MCP (Model Context Protocol) is Anthropic's open standard for connecting AI agents to external tools and data sources. In MARS, **all tooling goes through MCP** — every service exposes its capabilities as MCP tools. Agents receive only the Discovery Service initially, then query for further tools at runtime.

### MARS Federation — MARS ↔ MARS

No open standard for runtime-to-runtime agent federation exists yet. MARS uses a custom TCP protocol with JSON framing for cross-node agent sharing. This will be revisited once a standard emerges.

## How Discovery Works

LLMs do not receive a full tool list at startup. They receive only the **Discovery Service**:

```mermaid
sequenceDiagram
    participant LLM
    participant Server as MARS Server
    participant Discovery as Discovery Service (MCP)
    participant Tool as Any Service (MCP)

    Server->>LLM: spawn + here is discovery_service tool
    LLM->>Discovery: list_services()
    Discovery-->>LLM: [status, launcher, filesystem, ...]
    LLM->>Discovery: discover_service_capabilities("filesystem")
    Discovery-->>LLM: [read_file, write_file, list_dir, ...]
    LLM->>Tool: read_file(path="README.md")
    Tool-->>LLM: file contents
```

This keeps the context window small and lets services appear or disappear at runtime without re-prompting the LLM.

## Quick Start

Requires Python 3.11+.

```bash
# Terminal 1 — server (optionally pre-spawn an LLM agent)
python -m mars.server.main
python -m mars.server.main --provider ollama
python -m mars.server.main --provider ollama --model qwen3:4b

# Terminal 2 — TUI client
python -m mars.cli.main --remote 127.0.0.1:7432

# Or start both together (embedded mode)
python -m mars.cli.main --provider ollama
python -m mars.cli.main --provider zai --model glm-5.2
```

## Services

Two categories exist. **LLM Agents** are conversational inference backends. Everything else is an **MCP Service** — discovered and invoked through MCP protocol, regardless of whether it runs in-process, as a subprocess, or as a remote peer.

### LLM Agents

| Agent | Notes | Availability |
|-------|-------|-------------|
| `ollama` | Local Ollama server — free, no API key | TCP probe to `localhost:11434` |
| `copilot` | GitHub Copilot Chat | `gh auth token` or `COPILOT_API_KEY` env var |
| `zai` | z.AI (ZhipuAI) GLM models — GLM-5.2, GLM-4-Flash, etc. | `ZAI_API_KEY` env var |
| `mock` / `mock-tool` | Test-only — hidden from discovery | always |

The services panel shows a three-state dot per provider:
- 🟢 **Green** — provider is reachable / credentials resolved and agent is running
- ⚪ **White** — available (credentials present) but no agent spawned yet
- 🔴 **Red** — unavailable (Ollama not running, no API key set)

On connect, MARS automatically queries each available provider for its model list. Providers are shown as expandable rows (▶/▼) in the services panel.

### MCP Services

Everything else — builtin utilities, external MCP servers, A2A peers. All discovered and invoked through MCP protocol.

| Service | Auto-start | Status | Notes |
|---------|:----------:|--------|-------|
| `discovery` | ✅ | ✅ Working | **Bootstrap** — LLMs receive this on spawn; returns all services and tools |
| `status` | ✅ | ⚠️ Stub | Returns `not_implemented` — not yet wired to live MARSState |
| `launcher` | ✅ | ⚠️ Stub | Returns `not_implemented` — not yet wired to server spawn path |
| `cli` | ✅ | ✅ Working | CLI connection management |
| `profiler` | — | ✅ Working | Performance monitoring — `get_uptime` tool |
| `filesystem` | — | 🔧 Config needed | MCP filesystem server (stdio, requires config in `agents.ini`) |
| `federation` | — | 🔧 Config needed | A2A peer connection to remote MARS nodes (requires peer address) |

## TUI Commands

### Client-side (instant)

| Command | Status | Description |
|---------|--------|-------------|
| `/spawn <provider> [model]` | ✅ | Start a new LLM agent — e.g. `/spawn ollama qwen3:4b` |
| `/stop <agent-id>` | ✅ | Stop a running agent |
| `/agents` | ✅ | List running agents |
| `/agents available` | ✅ | List all known services and their availability |
| `/switch <agent-id>` | ✅ | Switch the active chat target |
| `/status [agent-id]` | ✅ | Show agent FSM state and strategy |
| `/verbose [agent-id]` | ✅ | Toggle verbose tool-call output |
| `/avatar <emoji\|n>` | ✅ | Set your avatar |
| `/new` | ✅ | Clear local conversation display |
| `/rewind` | ⚠️ | Remove last message pair — client display only, server context unchanged |
| `/compact` | ⚠️ | Summarise history — client display only, server context unchanged |
| `/context` | ✅ | Estimate token count for current context |
| `/read <file>` | ✅ | Read a file into the reply panel |
| `/copy` | ✅ | Copy last reply to clipboard |
| `/share [file]` | ✅ | Export session to a markdown file |
| `/search <query>` | ✅ | Search local chat history |
| `/ask <question>` | ✅ | Send a question (note: server history not excluded yet) |
| `/plan <task>` | ✅ | Ask for an implementation plan |
| `/instructions` | ✅ | Load `AGENTS.md` / `CLAUDE.md` as a message |
| `/echo text\|md\|void` | ✅ | Switch reply rendering mode |
| `/theme [name]` | ⚠️ | Set theme — stored but renderer not yet theme-aware |
| `/version` | ✅ | Show MARS version |
| `/help` | ✅ | Show command reference |
| `/quit` | ✅ | Exit |
| `@file` | ✅ | Inline-expand a file in your message |
| `!cmd` | ✅ | Run a shell command |

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Tab` | Cycle panel focus (chat → services → connections) |
| `↑` / `↓` | Scroll chat or navigate panel rows |
| `Enter` on provider | Expand / collapse model list |
| `Enter` on model | Spawn that model as an agent |

## Architecture

```mermaid
graph LR
    subgraph "MARS Server"
        Bus["Message Bus (TCP)"]
        Reg["Service Registry"]
        Disc["Discovery Service"]
        Launcher["Launcher Service"]
        Status["Status Service"]
    end

    subgraph "Protocol Adapters"
        AGUI["AG-UI Adapter"]
        A2A["A2A Adapter"]
        MCP["MCP Adapter"]
    end

    subgraph "External"
        Human["Human TUI"]
        Agent["LLM Agent"]
        Tool["MCP Tool Server"]
    end

    Human -->|AG-UI| AGUI --> Bus
    Agent -->|A2A| A2A --> Bus
    Bus --> MCP -->|MCP stdio| Tool
    Bus --- Disc
    Bus --- Launcher
    Bus --- Status
    Reg --> Disc
```

## Project Layout

```
mars/
├── common/          # Shared: wire framing, models, state, constants
├── cli/             # TUI client (AG-UI consumer)
│   ├── client.py    # Event loop, keyboard input, command dispatch
│   ├── commands.py  # /cmd implementations
│   ├── renderer.py  # Rich panel rendering (chat, services, connections)
│   └── nav.py       # Panel navigation + service row builder
└── server/
    ├── server.py    # TCP message bus + routing
    ├── protocols/   # Protocol adapters: AG-UI, A2A, MCP, MARS
    ├── services/
    │   ├── registry.py  # Service factory + availability probes
    │   ├── builtin/     # Discovery, Status, Launcher, Profiler, CLI (in-process)
    │   ├── llm/         # LLM wire agents: Ollama, Copilot, z.AI, Mock
    │   ├── mcp/         # MCP adapter + server wrappers
    │   └── a2a/         # A2A adapter
    └── federation.py    # MARS-to-MARS federation
```

## Environment Setup

Copy `.env.example` to `.env` and fill in any keys you need:

```bash
cp .env.example .env
```

| Variable | Provider | Notes |
|----------|----------|-------|
| `ZAI_API_KEY` | z.AI | Get from [platform.z.ai](https://platform.z.ai/) |
| `COPILOT_API_KEY` | Copilot | Only needed if not using `gh auth login` |
| *(none)* | Ollama | No key — just run `ollama serve` |

## Known Limitations / TODO

- `StatusService` and `LauncherService` return stub responses — they are not yet wired to live `MARSState` (see `TODO` comments in their source files)
- `/rewind` and `/compact` only affect the client-side display — the server-side LLM context window is unchanged until a wire command is added
- `/theme` stores the selection but the renderer does not yet apply it
- `/instructions` sends instruction files as a plain user message rather than injecting into the system prompt
- The `filesystem` MCP service requires an external `npx @modelcontextprotocol/server-filesystem` process (config in `agents.ini`)

## References

- AG-UI Protocol — <https://github.com/ag-ui-protocol/ag-ui>
- AG-UI Specification — <https://docs.ag-ui.com/>
- A2A Protocol — <https://google.github.io/A2A/>
- A2A Specification — <https://google.github.io/A2A/specification>
- MCP Specification — <https://modelcontextprotocol.io/specification>
- MCP Python SDK — <https://github.com/modelcontextprotocol/python-sdk>
- Ollama — <https://ollama.com/>
- z.AI API — <https://docs.z.ai/api-reference/introduction>
- GitHub Copilot API — <https://docs.github.com/en/copilot>


MARS is a **minimal, standards-aligned multi-agent runtime** where humans and AI agents share one live message bus, discover each other's capabilities, and collaborate through open protocols.

## Core Design Principle

**Everything is a service.** Tools, LLMs, data sources, connections — all exposed as services with a consistent interface. Agents discover capabilities at runtime through the Discovery Service rather than being hard-wired to specific tools.

## Protocol Stack

MARS implements three open standards, each with a distinct responsibility:

| Layer | Protocol | Purpose |
|-------|----------|---------|
| Human ↔ Client | [AG-UI](https://github.com/ag-ui-protocol/ag-ui) | Event-based human-agent interaction |
| Agent ↔ Agent | [A2A](https://google.github.io/A2A/) | Agent interoperability and task delegation |
| Agent ↔ Tools | [MCP](https://modelcontextprotocol.io/) | Service discovery and tool invocation |
| MARS ↔ MARS | Custom | Node federation — no open standard exists yet |

```mermaid
graph TB
    Human["👤 Human"]
    TUI["TUI / Frontend"]
    Server["MARS Server"]
    LLM["🤖 LLM Agent"]
    Svc["⚙️ Service / Tool"]
    Peer["🌍 Remote MARS Node"]

    Human -->|AG-UI| TUI
    TUI -->|AG-UI| Server
    LLM -->|A2A| Server
    Server -->|A2A| LLM
    Server -->|MCP| Svc
    Svc -->|MCP| Server
    Server <-->|Custom federation| Peer
```

### AG-UI — Human ↔ Client

> Spec: <https://github.com/ag-ui-protocol/ag-ui>  
> Docs: <https://docs.ag-ui.com/>

AG-UI is an open, lightweight, event-based protocol that standardises how AI agents connect to user-facing applications. MARS uses it for the channel between the human operator and the server so that any AG-UI-compatible frontend can connect.

### A2A — Agent ↔ Agent

> Spec: <https://google.github.io/A2A/>  
> SDK: <https://github.com/google/A2A>

A2A (Agent-to-Agent) is Google's open protocol for agent interoperability. It defines JSON-RPC 2.0 messaging, task lifecycle management, and Agent Cards for discovery. MARS uses A2A for all agent-to-agent communication.

### MCP — Agent ↔ Tools / Services

> Spec: <https://modelcontextprotocol.io/specification>  
> Python SDK: <https://github.com/modelcontextprotocol/python-sdk>

MCP (Model Context Protocol) is Anthropic's open standard for connecting AI agents to external tools and data sources. In MARS, **all tooling goes through MCP** — every service exposes its capabilities as MCP tools. Agents receive only the Discovery Service initially, then query for further tools at runtime.

### MARS Federation — MARS ↔ MARS

No open standard for runtime-to-runtime agent federation exists yet. MARS uses a custom TCP protocol with JSON framing for cross-node agent sharing. This will be revisited once a standard emerges.

## How Discovery Works

LLMs do not receive a full tool list at startup. They receive only the **Discovery Service**:

```mermaid
sequenceDiagram
    participant LLM
    participant Server as MARS Server
    participant Discovery as Discovery Service (MCP)
    participant Tool as Any Service (MCP)

    Server->>LLM: spawn + here is discovery_service tool
    LLM->>Discovery: list_services()
    Discovery-->>LLM: [status, launcher, filesystem, ...]
    LLM->>Discovery: discover_service_capabilities("filesystem")
    Discovery-->>LLM: [read_file, write_file, list_dir, ...]
    LLM->>Tool: read_file(path="README.md")
    Tool-->>LLM: file contents
```

This keeps the context window small and lets services appear or disappear at runtime without re-prompting the LLM.

## Quick Start

Requires Python 3.14+.

```bash
# Terminal 1 — server (optionally pre-spawn an LLM agent)
python -m mars.server.main
python -m mars.server.main --provider ollama
python -m mars.server.main --provider ollama --model qwen3:4b

# Terminal 2 — TUI client
python -m mars.cli.main --remote 127.0.0.1:7432

# Or start both together (embedded mode)
python -m mars.cli.main --provider ollama
```

## Services

Two categories exist. LLM Agents are conversational inference backends. Everything else is an **MCP Service** — discovered and invoked through MCP protocol, regardless of whether it runs in-process, as a subprocess, or as a remote peer.

### LLM Agents

| Agent | Notes |
|-------|-------|
| `ollama` | Local Ollama server |
| `copilot` | GitHub Copilot Chat |
| `mock` / `mock-tool` | Test-only — hidden from discovery |

### MCP Services

Everything else — builtin utilities, external MCP servers, A2A peers. All discovered and invoked through MCP protocol.

| Service | Auto-start | Notes |
|---------|:----------:|-------|
| `discovery` | ✅ | **Bootstrap** — LLMs receive this on spawn; returns all services and tools |
| `status` | ✅ | Runtime introspection — agents, problems, activity |
| `launcher` | ✅ | Spawn new LLM agents at runtime |
| `cli` | ✅ | CLI connection management |
| `filesystem` | — | MCP filesystem server (stdio, requires config) |
| `profiler` | — | Performance monitoring — uptime and metrics |
| `federation` | — | A2A peer connection to remote MARS nodes (requires config) |

## Architecture

```mermaid
graph LR
    subgraph "MARS Server"
        Bus["Message Bus (TCP)"]
        Reg["Service Registry"]
        Disc["Discovery Service"]
        Launcher["Launcher Service"]
        Status["Status Service"]
    end

    subgraph "Protocol Adapters"
        AGUI["AG-UI Adapter"]
        A2A["A2A Adapter"]
        MCP["MCP Adapter"]
    end

    subgraph "External"
        Human["Human TUI"]
        Agent["LLM Agent"]
        Tool["MCP Tool Server"]
    end

    Human -->|AG-UI| AGUI --> Bus
    Agent -->|A2A| A2A --> Bus
    Bus --> MCP -->|MCP stdio| Tool
    Bus --- Disc
    Bus --- Launcher
    Bus --- Status
    Reg --> Disc
```

## Project Layout

```
mars/
├── common/          # Shared: wire framing, models, state, constants
├── cli/             # TUI client (AG-UI consumer)
└── server/
    ├── server.py    # TCP message bus + routing
    ├── protocols/   # Protocol adapters: AG-UI, A2A, MCP, MARS
    ├── services/
    │   ├── builtin/ # Discovery, Status, Launcher, … (in-process)
    │   ├── llm/     # LLM wire agents (Ollama, Anthropic, Copilot)
    │   ├── mcp/     # MCP adapter + server wrappers
    │   └── a2a/     # A2A adapter
    └── federation.py  # MARS-to-MARS federation
```

## References

- AG-UI Protocol — <https://github.com/ag-ui-protocol/ag-ui>
- AG-UI Specification — <https://docs.ag-ui.com/>
- A2A Protocol — <https://google.github.io/A2A/>
- A2A Specification — <https://google.github.io/A2A/specification>
- MCP Specification — <https://modelcontextprotocol.io/specification>
- MCP Python SDK — <https://github.com/modelcontextprotocol/python-sdk>
