# 🌌 MARS — Multi-Agent Runtime System

MARS is a **chat server for humans and agents** with a service marketplace.

- Participants (humans and LLM-backed agents) join named **rooms** and talk.
- A **service marketplace** lets specialised agents advertise skills; any agent can discover and call them.
- Everything runs over a simple async message bus. The server exposes TCP, REST, and WebSocket interfaces.

---

## 🤖 What is MARS?

MARS is a Python asyncio platform where humans and agents share rooms and exchange messages. The LLM integration means agents understand natural conversation: `"Norbert: Hello Peter, what do you think?"` — Peter knows to respond, others may chime in. No special routing rules are needed.

> **Roadmap:** room strategies (everyone replies, random selection, chain communication, Contract Net Protocol task delegation) and governance / scope work will be layered on top of this foundation. The research papers in `papers/` define what each item means.

## ✨ What works today

- **Rooms** — humans and agents join named rooms; all messages fan out to every member.
- **LLM agents** — Anthropic Claude, GitHub Models / Copilot, Ollama (local), or offline mock.
- **Service marketplace** — `list_skills` / `use_skill` tools; auto-spawned agents: `clock`, `profiler`, `status`, `file`, `url`, `math` (SymPy), `scipy`, `ollama-models`.
- **Artifacts** — create, read, and share binary or text files between agents.
- **Federation** — message routing across multiple MARS nodes.
- **CLI** — three-pane terminal UI; connect to a server or run standalone.


---

## 🚀 Getting started

- **[SETUP.md](SETUP.md)** — prerequisites, install, configure providers, start the server.
- **[USER.md](USER.md)** — CLI walkthrough: spawn agents, chat, scopes, artifacts.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — runtime stack, service marketplace, scopes, game-theory FSM, providers.
- **[BUILD.md](BUILD.md)** — building, running tests, packaging a wheel, Git LFS.
- **[AGENTS.md](AGENTS.md)** — service-agent catalogue and wire protocol.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — project layout, coding conventions, how to add providers and tests.

### ⚡ Quick start

After `pip install -e ".[dev]"` (see [SETUP.md](SETUP.md)) — add `.[science]` for the SymPy/SciPy math agents, or `.[all]` for everything:

```bash
# Standalone CLI (in-process platform, no server needed)
python -m mars.cli.main --provider mock                        # offline test agent
python -m mars.cli.main --provider github-models               # free LLM (needs GITHUB_TOKEN)
python -m mars.cli.main --provider ollama                      # local Ollama — no API key, no limits
python -m mars.cli.main --provider ollama github-models        # both at once 🔀
python -m mars.cli.main --provider anthropic --model claude-3-5-sonnet-20241022  # Anthropic Claude (needs ANTHROPIC_API_KEY)
```

```bash
# Server + client (recommended for multi-client / persistent runs)
# Terminal 1 — start the headless server (auto-spawns free service agents)
python -m mars.srv.main                                        # echo bots only
python -m mars.srv.main --provider github-models               # + free GitHub Models LLM
python -m mars.srv.main --provider ollama                      # + local llama3.2 (unlimited, no key)
python -m mars.srv.main --provider ollama github-models        # + one agent per provider 🔀

# Terminal 2 — connect a CLI client
python -m mars.cli.main --remote localhost:7432
```

> The `pip install -e ".[dev]"` step also registers `mars` and `mars-server` console scripts. They work whenever your Python `Scripts/` (Windows) or `bin/` (Linux/macOS) directory is on `PATH` — but `python -m …` always works regardless of `PATH` configuration.
>
> **No API key?** Use `--provider ollama` with [Ollama](https://ollama.com) installed locally — completely free, no rate limits. See [SETUP.md](SETUP.md) for the full Ollama setup guide.

The server exposes TCP `7432` (JSON-line for CLI + agents), HTTP `7433` (REST), and WebSocket `7434` (browser UI). See [USER.md](USER.md) for the full command cheat sheet.

---

## 📈 Where MARS sits on the Hype Cycle

Gartner (2026) places agentic AI at the **Peak of Inflated Expectations**, warning that sustainable value requires:

1. **Alignment with real business objectives** — not demos for their own sake  
2. **Foundational infrastructure** — lifecycle, messaging, federation, governance  
3. **Operator-gated boundaries** — Python execution requires explicit human approval (no general "trust/risk" framework is implemented)  
4. **Realistic scoping** — iterative loops with defined exit criteria, not open-ended autonomy

MARS implements each of these:

| Gartner requirement | MARS feature |
|---------------------|-------------|
| Agent lifecycle management | `AMS` — INITIALIZING → ACTIVE → SUSPENDED → TERMINATED |
| Multi-agent communication | `MessageBus` — async unicast / broadcast / multicast |
| Execution boundary | Permission-gated `CodeExecutorAgent` — every Python run requires explicit operator approval (or an explicit auto-approve list). No general trust / risk framework is implemented. |
| Federated discovery | `GlobalDirectory` + `DomainDirectory` — two-level capability routing across domains and clusters |
| Goal-driven loops | `StateMachine` + `LoopContext` — build → review → fix → done, with exit conditions |
| Real business alignment | LLM agents with `send_message`, `list_agents`, and artifact tools — wired to real providers |

---

## 📖 Research foundations

The design is grounded in work by the author predating modern LLMs:

| Paper | Contribution to MARS |
|-------|----------------------|
| **Intelligent Mobile Agents in the Intra/Internet** (Nopper, 1997) | Foundational diploma thesis: mobile agent theory, transport, lifecycle, platform-independence — the direct predecessor of LARS and the entire MARS runtime model |
| **LARS** — Living Agents Runtime System (Nopper, 2000) | Platform-independence, lifecycle FSM, clustering, XML messaging. *(LARS originally included an agent-migration verb; MARS deliberately leaves that out — federation in MARS is message routing only.)* |
| **EMIKA** (Müller, Eymann, Nopper et al., 2004) | Real-time sensor-to-agent middleware, self-organising coordination, Ist/Soll-Zustand loop |
| **Agent-Based Counterparty Matching** (Lohmann, Nopper, Henning, 1998) | Hierarchical DIDF/DSDF discovery, specialist agents over a shared runtime |
| **Location-Aware Agent Retrieval** (Nopper, Kammerer, 2000) | Context-threaded, federated multi-source agent retrieval |
| **Patient Technology** (Müller, Nopper et al., ~2003) | Self-organisation requires an explicit governance framework (*Regelrahmen*) |

---

## 📚 References

- Axelrod, R. (1984). *The Evolution of Cooperation*. Basic Books.
- Nopper, N. (1997). *Intelligent Mobile Agents in the Intra/Internet*. Diploma thesis, Hochschule Furtwangen University (HFU).
- Lohmann, Nopper, Henning (1998). *Agent-Based Counterparty Matching in Financial Markets*.
- Nopper, Kammerer (2000). *Location-Aware Agent Retrieval*.
- Nopper, N. (2000). *LARS — Living Agents Runtime System*. AgentLink.
- Müller, Nopper et al. (~2003). *Patient Technology — Self-Organisation and Governance*.
- Müller, Eymann, Nopper et al. (2004). *EMIKA — Agent-Based Middleware for Real-Time Sensor Systems*.
- Shoham & Leyton-Brown (2009). *Multiagent Systems*. Cambridge University Press.
- Gartner, *Hype Cycle for Agentic AI*, 2026 — <https://www.gartner.com/en/articles/hype-cycle-for-agentic-ai>

