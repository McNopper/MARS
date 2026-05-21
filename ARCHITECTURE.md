# 🏛️ MARS Architecture

MARS is a **chat server for humans and agents**. It is a lean TCP router — nothing more.
Every participant (human CLI, LLM agent, service agent) connects via the same JSON-over-TCP
protocol, sends a `hello`, and the server routes messages between them.

For operational guides see:
- **[SETUP.md](SETUP.md)** — install, configure, run, start the server.
- **[BUILD.md](BUILD.md)** — building, testing, packaging.
- **[AGENTS.md](AGENTS.md)** — service-agent catalogue and wire protocol.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — project layout and conventions.

---

## Runtime stack

```
                          mars-server  (pure TCP router)
                          ├── TCP  :7432  ← all participants
                          ├── REST :7433  ← HTTP status API
                          ├── WS   :7434  ← Browser UI
                          └── Audit log   mars_audit.jsonl

Participants (all identical TCP protocol):
  mars (CLI)         → role="human"    human@1, human@2, …
  LLM wire agent     → role="agent"    llm.ollama@1, llm.anthropic@1, …
  Service agents     → role="agent"    svc.clock@1, svc.sympy@1, …
```

Every participant:
1. Opens a TCP connection to `:7432`
2. Sends `{"t":"hello","role":"…","name":"…","skills":[…]}`
3. Receives a roster of existing agents as `spawn` events + `{"t":"welcome","your_id":"…"}`
4. Sends `{"t":"msg","target":"<id>","text":"…"}` to route to another participant
5. Sends `{"t":"cmd","cmd":"spawn|join|part|…","args":{…}}` for server commands

The server **never runs agent code**. All agent logic lives in subprocesses.

### Spawning

All spawning happens **on the server**. Any participant can request it:

```
{"t":"cmd","cmd":"spawn","args":{"provider":"ollama","model":"llama3.2"}}
```

The server launches `python -m mars.runtime.services.llm_wire_agent --provider ollama …` as a
subprocess. That process connects back via TCP like any other agent.
Service agents are spawned the same way from `mars/runtime/agents/agents.ini`.

```
mars --remote HOST:PORT   → skips subprocess, connects directly to a running server
```

---

## 💬 Rooms

All communication happens in named **rooms**. Any participant can join or leave at any time.

```
human@1:       Hello everyone!
llm.ollama@1:  Hi! How can I help?
human@1:       Peter, what do you think about X?
llm.ollama@2:  I'd add that ...    ← another participant chimes in
```

- **Join** — `{"t":"cmd","cmd":"join","args":{"room":"roomname"}}`
- **Leave** — `{"t":"cmd","cmd":"part","args":{"room":"roomname"}}`
- **Send to room** — `{"t":"msg","target":"#roomname","text":"…"}` — server fans out to all members except the sender
- **Despawn** — removes all room memberships automatically

Multiple CLI users get unique identities: `cli-user@1`, `cli-user@2`, etc.

> **Future:** room broadcast strategies (round-robin, everyone-must-reply, random selection) will be added as optional per-room policies.

---

## 🔧 Service agents

Service agents expose specialised skills (math, profiling, file I/O, spawning, …).
Built-in agents run as **MCP stdio subprocesses** managed by the server — they never
open a TCP connection. Advanced agents that need to send server commands can still use
the TCP wire protocol.

```
                   mars-server :7432
                        │
        ┌───────────────┼────────────────────┐
        │               │                    │
  human@1          svc.sympy@1         svc.profiler@1
  (CLI terminal)   skills: solve_math, skills: get_profile,
                   math, sympy, …     profiler, cpu, …
```

See [AGENTS.md](AGENTS.md) for the MCP protocol, `_mars_cmd` envelope, and ready-made implementations.

### Skill routing

The server maintains a skill→agent_id index from each agent's `hello` registration.
LLM agents send `{"t":"cmd","cmd":"list_skills"}` to discover available skills, then route
`msg` directly to the matching `agent_id`. Artifacts returned by service agents are forwarded
to the requesting participant.

---

## 🗺️ Domain Scopes — knowledge arenas (data model, not yet active)

> **Status:** data model and loader implemented; runtime skill-routing and problem orchestration are **not yet implemented**.

The `mars/storage/scopes/` package defines the data model:

- `Scope` — static domain definition loaded from a `.md` file (id, title, document, required_skills, parent_id)
- `Problem` — a challenge posed within one or more scopes (status lifecycle: open → assigned → in_progress → solved | closed)
- `Solution` / `DomainContribution` — composite answer subdivided per agent

**What works today:** `ScopeStore` loads `.md` files from `scopes/`; the REST API exposes `GET /scopes`. The CLI can display scope metadata.

**Not yet implemented:** automatic agent assignment based on `required_skills`, problem lifecycle management, solution synthesis, and competence-tier routing.

The planned 6-tier knowledge topology (Formal Sciences → Natural Sciences → Human & Social → Human Experience → Technology & Infrastructure → Global Challenges) is defined in `scopes/` as `.md` files but is not wired into any agent dispatch logic yet.

---

## 🎮 Agent FSM metadata (fields only, no engine)

> **Status:** `AgentRecord` stores `fsm_state` and `fsm_strategy` fields; the CLI **Agents** panel displays them for conversational agents and the **MCP Servers** panel displays them for service agents. There is **no platform FSM engine** — transitions are not driven by MARS.

Agents can self-report their state via `{"t":"fsm","fsm_state":"…","fsm_strategy":"…"}` events. The CLI renders these. Planned state presets and strategies (COOPERATIVE, TIT_FOR_TAT, NASH_SEEKING, etc.) are documented in the research papers but not implemented.

---

Built-in providers are implemented in `mars/client/providers/`:

| Provider | Name | Free | Extended thinking | Adaptive thinking | Prompt caching |
|----------|------|------|-------------------|-------------------|----------------|
| Mock (offline) | `mock` / `mock-tool` | ✅ offline, no key | — | — | — |
| Anthropic Claude | `anthropic` / `claude` | ❌ API key required | ✅ | ✅ | ✅ |
| GitHub Copilot | `copilot` | ✅ subscription | — | — | — |
| Ollama (local) | `ollama` | ✅ local, no key, no limits | — | — | — |

Common alias: `claude` → `anthropic`.

Anthropic defaults to `claude-sonnet-4-6`; `claude-opus-4-7` automatically uses adaptive thinking.

---

## 🤖 Agent types

Agents differ in how they connect to the server. LLM wire agents and CLI users connect via TCP. Built-in service agents run as MCP stdio subprocesses managed by the server — they never open a TCP connection. All use the same `agent_type` classification:

| Icon | `agent_type` | Description |
|------|-------------|-------------|
| 🤖 | `LLMAgent` | LLM wire agent — `mars/runtime/services/llm_wire_agent.py` |
| 🔧 | `ServiceAgent` | Service agent — profiler, sympy, scipy, file, url, custom |
| 👤 | `HumanUser` | CLI terminal — `mars/client/cli/main.py` |

LLM wire agents maintain conversation history in-process. They are reactive by default;
proactive (goal-directed autopilot) behaviour is a future extension.

