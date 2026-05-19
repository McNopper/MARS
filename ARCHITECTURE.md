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
  Service agents     → role="agent"    svc.clock@1, svc.math@1, …
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

The server launches `python -m mars.services.llm_wire_agent --provider ollama …` as a
subprocess. That process connects back via TCP like any other agent.
Service agents are spawned the same way from `agents.ini`.

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
  human@1          svc.math@1         svc.profiler@1
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

## 🗺️ Domain Scopes — knowledge arenas

A **Scope** (`mars/scopes/scope.py`) is a *static* domain definition loaded from a `.md` file.
Scopes are permanent knowledge arenas — they carry no runtime lifecycle.
**Problems** are posed *within* one or more Scopes; agents search for Solutions to Problems.

```
Scope  (static .md file)        Problem  (active challenge)        Solution  (composite)
────────────────────────        ─────────────────────────          ──────────────────────
id, title, document             id, title, description             contributions: list[
required_skills                 scope_ids: list[str]               │  DomainContribution ]
parent_id                       status: open→assigned→             summary
                                  in_progress→solved|closed        is_complete: bool
                                required_skills
                                agents: list[str]
```

A **Solution** is *subdivided* into **DomainContributions** — one per participating agent.
This mirrors the Contract Net Protocol (Smith 1980): Problem ↔ task announcement,
DomainContribution ↔ contractor result; and EMIKA sub-scope decomposition (Müller et al. 2004).

### Domain topology — 6-tier hierarchy

The `scopes/` directory implements a universal knowledge topology grounded in DDC, UDC,
Wikipedia's Outline of Knowledge, and the MARS research lineage:

```
U0 — Universal
│
├─ TIER 1  FORMAL SCIENCES          PH1 Philosophy · M1 Math · L1 Language
│                                   CS1 Computer Science · AI1 Artificial Intelligence
│
├─ TIER 2  NATURAL SCIENCES         SC1 Science[meta] · P1 Physics · B1 Biology
│                                   C1 Climate & Earth
│
├─ TIER 3  HUMAN & SOCIAL           PS1 Psychology · SO1 Sociology · EC1 Economics
│                                   ET1 Ethics · SR1 Spirituality · PL1 Political Science
│
├─ TIER 4  HUMAN EXPERIENCE         FA1 Family · LV1 Love · SX1 Sexuality
│                                   FF1 Flora & Fauna · SP1 Sports · AR1 Arts · HB1 Hobbies
│
├─ TIER 5  TECHNOLOGY & INFRA       IN1 Internet · E1 Energy · CM1 Communication
│                                   TR1 Transport · T1 Trading & Markets
│
└─ TIER 6  GLOBAL CHALLENGES        F1 Food Security · K1 Conflict · H1 Health
```

> **Tier 4 note:** Flora & Fauna (`FF1`) sits in Human Experience because the human
> *relationship* with plants and animals (stewardship, biophilia, husbandry) is
> experiential. Scientific study of life belongs in Tier 2 (`B1 Biology`, `C1 Climate`).

### Skill-match routing for scopes

The server's skill index maps each skill keyword to the best registered `agent_id` by
first-registered order. Future: competence-tier ranking.

---

## 🎮 Game-theory FSM (wire agent library)

Wire agents (LLM subprocesses) can embed a finite-state machine. States and strategies are declared in the wire agent and broadcast as status events:

```
States (preset: lifecycle)    IDLE → THINKING → ACTING → WAITING → DONE
States (preset: negotiation)  BIDDING → NEGOTIATING → SETTLING → AGREED / REJECTED
States (preset: iterative)    PLANNING → EXECUTING → REVIEWING → DONE / GIVING_UP

Strategies   COOPERATIVE · COMPETITIVE · TIT_FOR_TAT · GRIM_TRIGGER
             PAVLOV · MINIMAX · RANDOM · NASH_SEEKING · MDP
```

State transitions are broadcast as `{"t":"status","agent_id":"…","state":"…"}` events.

---

Built-in providers are implemented in `mars/providers/`:

| Provider | Name | Free | Extended thinking | Adaptive thinking | Prompt caching |
|----------|------|------|-------------------|-------------------|----------------|
| Mock (offline) | `mock` | ✅ offline, no key | — | — | — |
| Anthropic Claude | `anthropic` / `claude` | ❌ API key required | ✅ | ✅ | ✅ |
| GitHub Models / Copilot | `github-models` / `copilot` | ✅ free tier / subscription | — | — | — |
| Ollama (local) | `ollama` | ✅ local, no key, no limits | — | — | — |

Anthropic defaults to `claude-sonnet-4-6`; `claude-opus-4-7` automatically uses adaptive thinking.

Common aliases: `github` / `ghm` → `github-models`, `claude` → `anthropic`.

---

## 🤖 Agent types

All agents are TCP subprocesses. They differ only in the `agent_type` field of their `hello`:

| Icon | `agent_type` | Description |
|------|-------------|-------------|
| 🤖 | `LLMAgent` | LLM wire agent — `mars/services/llm_wire_agent.py` |
| 🔧 | `ServiceAgent` | Service agent — profiler, math, file, url, custom |
| 👤 | `HumanUser` | CLI terminal — `mars/cli/main.py` |

LLM wire agents maintain conversation history in-process. They are reactive by default;
proactive (goal-directed autopilot) behaviour is a future extension.

---

## 🌐 Federation — multi-node message routing

When two MARS servers are connected, `FederationCluster.route_remote()` handles transparent
message routing between nodes. From the perspective of all other agents, remote agents appear
local — they just have a different address in their identifier.

```
Node A  (192.168.1.1:7432)          Node B  (192.168.1.2:7432)
├── MARSServer                       ├── MARSServer
│   └── federation-agent@1 ──────────┼── federation-agent@1
│       (routes A↔B transparently)   │
└── Agents                           └── Agents
    llm.ollama@1                          llm.anthropic@1
    svc.math@1                            svc.profiler@1
```

An agent on Node A addresses a remote peer as `llm.anthropic@192.168.1.2` — the
federation cluster resolves the address and forwards the message. The target agent
sees it as a normal `msg` from a peer.

Agent **migration** (beaming an agent with its full state to a remote node) is a separate
optional feature built on top of federation routing.

---

## 🐍 Code Execution — permission-gated Python

`/spawn code` starts `svc.code@1` as a TCP service agent with skills `python`, `execute`, `code`.

### Permission flow

```
LLM wire agent          svc.code@1 (TCP)            CLI operator
    │                          │                          │
    │── msg: run_python ───────►│                          │
    │                           │── permission-request ───►│  (broadcast)
    │                           │                          │── /approve [id]
    │                           │── subprocess.run(…)      │
    │◄── msg: {output:…} ───────│                          │
    │                           │── /deny [id]             │
    │◄── msg: {status:denied} ──│◄─────────────────────────│
```

```
/permissions          — list pending requests
/approve [id]         — approve a request
/deny [id]            — deny a request
```

