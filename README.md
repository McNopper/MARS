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

- **Rooms** — humans and agents join named rooms; messages fan out to every member.
- **LLM agents** — Anthropic Claude, GitHub Copilot, Ollama (local), or offline mock.
- **Service marketplace** — MCP stdio subprocesses; auto-spawned: `clock`, `profiler`, `status`, `file`, `url`, `math` (SymPy), `scipy`, `ollama-models`, `launcher`.
- **External MCP servers** — any third-party MCP server (e.g. GitHub MCP) plugs in via `agents.ini` with zero Python code; multi-parameter tool schemas are forwarded verbatim.
- **Artifacts** — create, read, and share binary or text files between agents.
- **CLI** — three-pane terminal UI; connect to a server or run standalone.

### 🗺️ On the roadmap (from the papers, not yet implemented)

- **Domain scopes** — knowledge arenas that route problems to agents with matching skills.
- **Agent FSM engine** — platform-driven lifecycle transitions (idle → active → suspended → migrating).
- **Federation** — transparent message routing between MARS nodes; remote agents appear local.
- **Mobile agents (beaming)** — migrate a live agent with its full state to a remote node and back.

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
# Standalone CLI (in-process platform, no server needed)
python -m mars.client.cli.main --provider mock                        # offline test agent
python -m mars.client.cli.main --provider ollama                      # local Ollama — no API key, no limits
python -m mars.client.cli.main --provider anthropic --model claude-sonnet-4-6  # Anthropic Claude (needs ANTHROPIC_API_KEY)
```

```bash
# Server + client (recommended for multi-client / persistent runs)
# Terminal 1 — start the headless server (auto-spawns free service agents)
python -m mars.runtime.server.main                                        # echo bots only
python -m mars.runtime.server.main --provider ollama                      # + local llama3.2 (unlimited, no key)

# Terminal 2 — connect a CLI client
python -m mars.client.cli.main --remote localhost:7432
```

> The `pip install -e ".[dev]"` step also registers `mars` and `mars-server` console scripts. They work whenever your Python `Scripts/` (Windows) or `bin/` (Linux/macOS) directory is on `PATH` — but `python -m …` always works regardless of `PATH` configuration.
>
> **No API key?** Use `--provider ollama` with [Ollama](https://ollama.com) installed locally — completely free, no rate limits. See [SETUP.md](SETUP.md) for the full Ollama setup guide.

The server exposes TCP `7432` (JSON-line for CLI + agents), HTTP `7433` (REST), and WebSocket `7434` (browser UI). See [USER.md](USER.md) for the full command cheat sheet.

---

## 📖 Research foundations

The architecture is grounded in work by the author predating modern LLMs. These papers define the roadmap — features are added to MARS as they are implemented, not before.

| Paper | Relevance |
|-------|-----------|
| **Intelligent Mobile Agents in the Intra/Internet** (Nopper, 1997) | Diploma thesis: mobile agent lifecycle and platform-independence — the conceptual predecessor of MARS |
| [**LARS** — Living Agents Runtime System](papers/AgentLink_living_agents_runtime_system.pdf) (Nopper, 2000) | Platform-independence, lifecycle, clustering, XML messaging |
| [**EMIKA**](papers/EMIKA_System_Architecture_and_Prototypic_Realization.pdf) (Müller, Eymann, Nopper et al., 2004) | Sensor-to-agent middleware, self-organising coordination |
| [**Agent-Based Counterparty Matching**](papers/Agent-Based_Counterparty_Matching_in_Agent-Based_Trading.pdf) (Lohmann, Nopper, Henning, 1998) | Specialist agent discovery over a shared runtime |
| [**Location-Aware Agent Retrieval**](papers/Method_computer_and_computer_program_product_for_access_to_location_dependent_data.pdf) (Nopper, Kammerer, 2000) | Federated, context-threaded agent retrieval |
| [**Patient Technology**](papers/Patient_Technology_for_Impatiently_Patients.pdf) (Müller, Nopper et al., ~2003) | Governance framework for self-organising systems |

---

## 📚 References

- Nopper, N. (1997). *Intelligent Mobile Agents in the Intra/Internet*. Diploma thesis, Hochschule Furtwangen University (HFU).
- Lohmann, Nopper, Henning (1998). *Agent-Based Counterparty Matching in Financial Markets*.
- Nopper, Kammerer (2000). *Location-Aware Agent Retrieval*.
- Nopper, N. (2000). *LARS — Living Agents Runtime System*. AgentLink.
- Müller, Nopper et al. (~2003). *Patient Technology — Self-Organisation and Governance*.
- Müller, Eymann, Nopper et al. (2004). *EMIKA — Agent-Based Middleware for Real-Time Sensor Systems*.

