# 🌌 MARS — Multi-Agent Runtime System

MARS is an **open multi-agent runtime** where humans and heterogeneous AI agents share a live message bus, discover each other's skills, and collaborate — without central orchestration, hard-wired pipelines, or a single controlling LLM.

---

## 🤖 What is MARS?

Most "multi-agent" frameworks are glorified function-call chains: one orchestrator LLM decides which tool to call next, and every other "agent" is really just a named tool. MARS is different.

**The key ideas:**

- **Flat peer topology.** Every participant — human, LLM agent, or service agent — connects via the same JSON-over-TCP protocol, registers its skills with a `hello`, and is addressable by any other participant. There is no master controller.
- **Natural language routing.** LLM agents read the full room conversation and decide for themselves whether to respond. `"Norbert: Hello Peter, what do you think?"` — Peter responds because it understands the conversation, not because a router dispatched a function call to it.
- **Open service marketplace.** Service agents (math, file I/O, profiler, URL fetch, …) advertise skills on the bus. Any LLM agent discovers them via `list_skills` and calls them as MCP tool calls — built-in and third-party servers (e.g. GitHub MCP) are handled identically.
- **Research grounding predating LLMs.** The architecture traces directly to LARS (Nopper, 2000) and earlier work on mobile agents, platform-independence, and federated agent discovery. These papers define the roadmap; features are implemented as they become technically feasible, not before.

### ✨ What works today

**Core platform**
- **Rooms** — humans and agents join named rooms; messages fan out to every member.
- **LLM agents** — Anthropic Claude, GitHub Copilot, Ollama (local), or offline mock. All share one common provider interface.
- **THINKING spinner** — braille animation in the TUI when an agent is processing.
- **Artifacts** — create, read, and share binary or text files between agents.
- **CLI** — three-pane terminal UI (`mars` / `python -m mars.client.cli.main`); connect to a server or run standalone.

**Service marketplace** — all auto-spawned at server start (MCP stdio):

| Agent | Skills | Notes |
|-------|--------|-------|
| `clock` | time, location, datetime | Returns current time and geolocation as JSON |
| `profiler` | profiler, memory, cpu, performance | CPU/RAM/process stats |
| `status` | status, introspection, runtime | Live platform snapshot |
| `sympy` | math, solve, equation, algebra, calculus, … | Exact symbolic math (SymPy) |
| `scipy` | scipy, numerical, optimize, linalg, stats, ode, … | Numerical math and statistics |
| `file` | file, read, write, fileio, storage, filesystem | Sandboxed file I/O in `artifacts/fileio/` |
| `url` | url, fetch, http, web, get, post | HTTP GET/POST any public URL |
| `ollama-models` | models, list-models, ollama-models | Lists locally installed Ollama models |
| `launcher` | spawn_agent, launch, create_agent | Agent-to-agent spawning via MCP tool |
| `git` | git, diff, status, log, add, commit, branch, blame | Git operations via gitpython |
| `memory` | remember, recall, forget, memory_list | Cross-session key-value memory (`~/.mars/memory.json`) |
| `session` | save_session, load_session, list_sessions, session | Save/restore conversations in `~/.mars/sessions/` |
| `filesystem` *(auto, needs Node.js)* | read_file, write_file, edit_file, list_directory, … | Surgical local file access via `npx @modelcontextprotocol/server-filesystem` |
| `shell` *(on-demand)* | shell, run, exec, bash, terminal | Shell command execution (stdout/stderr/exit_code) |
| `scheduler` *(on-demand)* | schedule_after, schedule_every, after, every | One-shot and recurring prompt scheduling |
| `github` *(on-demand)* | search_repositories, create_issue, list_pull_requests, … | GitHub API — requires `GITHUB_PERSONAL_ACCESS_TOKEN` + binary |

**External MCP servers** — any third-party MCP server (e.g. GitHub MCP) plugs in via `agents.ini` with zero Python code; multi-parameter tool schemas are forwarded verbatim.

**CLI commands** — full feature set, see [USER.md](USER.md) for the cheat sheet:

| Category | Commands |
|----------|----------|
| Agents | `/spawn`, `/stop`, `/agents`, `/switch` |
| Rooms | `/join`, `/part`, `/list` |
| Conversation | `/new`, `/compact`, `/rewind`, `/ask`, `/plan` |
| Workspace | `@file`, `!cmd`, `/copy`, `/context`, `/instructions`, `/share`, `/search` |
| Rendering | `/echo`, `/theme`, `/verbose`, `/read`, `/avatar` |
| Other | `/status`, `/version`, `/help`, `/quit` |

### 🗺️ On the roadmap (from the papers, not yet implemented)

- **Multiline input** — `Ctrl+G` to open `$EDITOR` for multi-line prompts.
- **LSP / code intelligence** — live symbol lookup and diagnostics from a language server.
- **Scheduled prompt execution** — the scheduler agent records schedules; automatic dispatch is not yet wired.
- **Domain scopes (active routing)** — data model and CLI display exist; automatic agent assignment by skill is not yet implemented.
- **Agent FSM engine** — platform-driven lifecycle transitions (idle → active → suspended → migrating).
- **Federation** — transparent message routing between MARS nodes; remote agents appear local.
- **Mobile agents (beaming)** — migrate a live agent with its full state to a remote node and back.

---

## 📊 Feature comparison

MARS is designed as a **provider-agnostic replacement** for tools like GitHub Copilot CLI and Anthropic Claude CLI. The table below shows the current feature parity.

### Daily-use CLI features

| Feature | Copilot CLI | Claude CLI | MARS |
|---------|:-----------:|:----------:|:----:|
| Multi-turn conversation | ✅ | ✅ | ✅ |
| Thinking / working indicator | ✅ | ✅ | ✅ animated spinner |
| `@file` — inline file context | ✅ | ✅ | ✅ |
| `!cmd` — shell shortcut | ✅ | ✅ | ✅ |
| `/copy` — copy reply to clipboard | ✅ | ✅ | ✅ |
| `/new` — clear conversation | ✅ | ✅ | ✅ |
| `/context` — token count estimate | ✅ | ✅ | ✅ |
| `/compact` — summarise and compress | ✅ | ✅ | ✅ |
| `/rewind` — undo last message pair | ✅ | ✅ | ✅ |
| `/share` — export to Markdown | — | ✅ | ✅ |
| `/search` — search history | — | ✅ | ✅ |
| `/ask` — ephemeral side question | — | ✅ | ✅ |
| `/plan` — request implementation plan | ✅ | ✅ | ✅ |
| `/instructions` — load project rules | ✅ (Copilot instructions) | ✅ (CLAUDE.md) | ✅ (AGENTS.md, CLAUDE.md, copilot-instructions.md) |
| Session save / restore | ✅ | ✅ | ✅ session agent |
| Cross-session memory | — | ✅ | ✅ memory agent |
| Git operations | — | — | ✅ git agent |
| Shell execution | ✅ | ✅ | ✅ shell agent |
| Scheduled prompts | — | — | ✅ scheduler agent (records only; auto-dispatch not yet wired) |
| Multiline input (Ctrl+G / editor) | ✅ | ✅ | ❌ planned |
| LSP / code intelligence | — | ✅ | ❌ planned |

### MARS-exclusive capabilities

| Feature | Description |
|---------|-------------|
| **Multi-provider** | Anthropic Claude, GitHub Copilot, and Ollama simultaneously in the same session |
| **Group chat rooms** | Humans and multiple agents in the same room, messaging each other naturally |
| **Agent-to-agent spawning** | LLM agents can spawn other agents via the `launcher` MCP tool |
| **Service marketplace** | Auto-discovered skill registry; agents call services by skill name, not hard-coded IDs |
| **Science agents** | SymPy (exact symbolic) and SciPy (numerical) math, built-in and auto-spawned |
| **External MCP servers** | Any MCP stdio server (GitHub, databases, …) plugs in via a one-line `agents.ini` entry |
| **Zero API-SDK dependencies** | Only `httpx` + `anthropic` SDK; all providers use the same OpenAI-compatible HTTP path where possible |
| **Federation** *(planned)* | Transparent multi-node routing so remote agents appear local |

---

## 🚀 Getting started

- **[SETUP.md](SETUP.md)** — prerequisites, install, configure providers, start the server.
- **[USER.md](USER.md)** — CLI walkthrough: spawn agents, chat, artifacts.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — runtime stack, service marketplace, providers.
- **[BUILD.md](BUILD.md)** — building, running tests, packaging a wheel, Git LFS.
- **[AGENTS.md](AGENTS.md)** — service-agent catalogue and wire protocol.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — project layout, coding conventions, how to add providers and tests.

### ⚡ Quick start

After `pip install -e ".[dev]"` (see [SETUP.md](SETUP.md)):

```bash
# Standalone CLI — one provider
python -m mars.client.cli.main --provider mock                     # offline, no setup needed
python -m mars.client.cli.main --provider ollama                   # local Ollama, free, no API key
python -m mars.client.cli.main --provider copilot                  # GitHub Copilot (gh auth login once)
```

```bash
# Two providers side-by-side — Ollama + Copilot in the same session
# Terminal 1 — headless server
python -m mars.runtime.server.main

# Terminal 2 — spawn both agents, then chat with either one
python -m mars.client.cli.main --remote localhost:7432
# Inside the CLI:
/spawn ollama              # local llama3.2, unlimited, no key
/spawn copilot gpt-4o-mini # GitHub Copilot, fast model
# Switch between agents with /switch, or send to both in the same room
```

```bash
# Server + client (recommended for persistent runs)
# Terminal 1
python -m mars.runtime.server.main --provider ollama   # server starts with Ollama pre-spawned

# Terminal 2
python -m mars.client.cli.main --remote localhost:7432
```

> The `pip install -e ".[dev]"` step also registers `mars` and `mars-server` console scripts. They work whenever your Python `Scripts/` (Windows) or `bin/` (Linux/macOS) directory is on `PATH` — but `python -m …` always works regardless of `PATH` configuration.
>
> **No API key?** Use `--provider ollama` with [Ollama](https://ollama.com) installed locally — completely free, no rate limits. See [SETUP.md](SETUP.md) for the full setup guide.

The server exposes TCP `7432` (JSON-line for CLI + agents), HTTP `7433` (REST), and WebSocket `7434` (browser UI). See [USER.md](USER.md) for the full command cheat sheet.

---

## 📚 References

The architecture is grounded in work by the author predating modern LLMs. These papers define the roadmap — features are added to MARS as they are implemented, not before.

| Reference | Relevance |
|-----------|-----------|
| Nopper, N. (1997). *Intelligent Mobile Agents in the Intra/Internet*. Diploma thesis, HFU. | Mobile agent lifecycle and platform-independence — conceptual predecessor of MARS |
| [Nopper, N. (2000). *LARS — Living Agents Runtime System*. AgentLink.](papers/AgentLink_living_agents_runtime_system.pdf) | Platform-independence, lifecycle, clustering, XML messaging |
| [Müller, Eymann, Nopper et al. (2004). *EMIKA*.](papers/EMIKA_System_Architecture_and_Prototypic_Realization.pdf) | Sensor-to-agent middleware, self-organising coordination |
| [Lohmann, Nopper, Henning (1998). *Agent-Based Counterparty Matching*.](papers/Agent-Based_Counterparty_Matching_in_Agent-Based_Trading.pdf) | Specialist agent discovery over a shared runtime |
| [Nopper, Kammerer (2000). *Location-Aware Agent Retrieval*. European Patent.](papers/Method_computer_and_computer_program_product_for_access_to_location_dependent_data.pdf) | Federated, context-threaded agent retrieval |
| [Müller, Nopper et al. (~2003). *Patient Technology*.](papers/Patient_Technology_for_Impatiently_Patients.pdf) | Governance framework for self-organising systems |

