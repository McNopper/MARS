# MARS — Planning & Roadmap

> The vision and principles live in [`README.md`](README.md). This is the **status**, the **roadmap**, and the **prior-art survey**.

## Vision in one paragraph

MARS is a multi-agent runtime expressed as a **world**: an open place where humans and AI agents meet as equal avatars in rooms and coordinate by talking. One door — **MCP** — and every actor walks through it. Any MCP-speaking agent is the pilot (opencode is the tested example); MARS ships no client and no LLM layer. The world is a directory of text files; `look`/`listen` read, `say` appends, `take`/`drop` move files.

## Status — Phase 0 done

A minimal, tested, **stable** world:

- `mars/world/world.py` — `World`: rooms + artifacts + inventories as plain text files (pure logic).
- `mars/world/server.py` — `WorldSession` (world + in-memory presence) wrapped as a FastMCP server. The single door.
- Verbs live: `look · listen · say · go · examine · take · drop · inventory · create · modify · destroy · rooms`.
- Items: create (with `kind`: item/fixed/room) / examine / take / drop / modify / destroy; taking is exclusive; fixed items can't be taken; `modify` grows a note in place. An item's content may be a URL/path the citizen fetches (a real-document handle).
- Rooms seeded (`lobby`, `library`); admin-authored via the engine / text files.
- opencode wiring: `opencode.jsonc` (the `mars` MCP server) + `.opencode/skills/mars-citizen/SKILL.md`.
- Tests: 52 unit + 2 end-to-end (stdio + SSE, drive the door as a real MCP client, marked `slow`).
- Concurrency: a **single-worker tick service** drains a command queue (~100 ms) and prunes expired talk (~1000 ms); all world access — including the prune — runs on that one thread, so it can never race. (The engine also keeps an in-process lock for direct/test use; run one server per world directory.)
- Ephemeral talk: each utterance is timestamped; lines older than the TTL (default 60 s; `--talk-ttl`, `0` = off) are pruned. Items stay durable.

The previous multi-agent **runtime** code (`mars/cli`, `mars/server`, `mars/common`) has been removed. MARS is now just the world.

## Model

- **A room is an abstract boundary** — a place, a sea, a chest, or an abstract context like a task. The **map** is just the outermost room. So a room *is* a context boundary.
- **Plain-text persistence** — no database; `world/` is `rooms/*.md` + `artifacts/<room>/` + `avatars/<avatar>/`. Durable state is text; only live presence is in memory.
- **One door (MCP), no parser** — natural language becomes tool calls inside the connecting agent, never inside MARS. opencode is the tested pilot; any MCP client works.

## Roadmap

The stable core (verbs, items, rooms, transports, in-session multi-avatar) is done — see **Status** above. Forward work, grouped by theme:

### Next — model completeness
*(Done — item kinds, modify-in-place, create-makes-rooms, and real-document handles all shipped. Kept here as a record.)*
- ~~**Item kinds.**~~ Portable (default), *fixed* (can't be taken), and *room* (non-portable, enterable) via `create(kind=...)`.
- ~~**Modify items in place.**~~ `modify` grows a note/whiteboard in place.
- ~~**`create` makes rooms.**~~ `create(kind="room")` unifies room + item authoring.
- ~~**Items as real-document handles.**~~ An item's content may be a URL/path; the citizen fetches it on `examine` (MARS stays dumb).

### Then — the cast (multi-agent collaboration)
- ~~**Example skills.**~~ Shipped: `dungeon-master`, `product-owner`, `junior-programmer` in `.opencode/skills/` (alongside `mars-citizen`).
- ~~**Cheap-router Dungeon Master.**~~ The `dungeon-master` skill instructs the DM to route hard asks to a smarter avatar by talking to it — the routing is LLM-driven via the skill, no code needed.
- ~~**Async by default.**~~ Already works: leave a question via `say`; a specialist who later enters and `listen`s catches up and answers. Documented in the examples.
- ~~**Persistent residents.**~~ Not a MARS feature — a deployment pattern. A persistent Dungeon Master or specialist is simply an always-on agent instance (e.g. opencode with a skill) connected to the world via the SSE network door and left running. MARS stays dumb; the pilot owns the lifecycle. No architecture change.

### Later — scale & robustness
- **Context curation.** Summarise/compact a busy room's transcript so it stays within a context window.
- **Auth & malicious-agent hardening.** A topic on its own — authentication, authorisation, avatar identity verification, and defence against malicious agents on the network door. Clearly future work; the door stays loopback-only until this is designed.
- **Presence persistence / crash recovery.** What happens to presence if MARS crashes or restarts — currently in-memory, resets on restart. Whether to persist who's-where (and how to reconcile stale entries) is an open question for future work.
- **Presence expiry.** Clear avatars whose clients have disconnected — today they linger in `look` until the server restarts. Needs a heartbeat/TTL (MCP gives no disconnect signal to the verbs).
- ~~**Observability.**~~ Not a MARS concern. The per-room transcripts already record everything said; if you want broader logging or audit, that's an outside task (tail the files, sync them to a log system, etc.). MARS stays dumb.

## Prior-art survey (does this already exist?)

**Verdict: the fusion does not exist.** Researched 2026-07-10 across the three MCP directories (official repo, Glama ~53.9k servers, mcp.so) plus the multi-agent-world landscape. Search engines were largely bot-blocked, so this rests on direct primary-source fetches — a quiet competitor could still appear, but as of now:

- **Spatial meeting-place** → MOO/MUD lineage (LambdaMOO): open, rooms, `take`/`drop`, humans as avatars. But it owns its character DB and has no LLM-native agent parity or MCP binding.
- **Open plug-in / pilot-owns-lifecycle** → A2A / MCP / FIPA ACL: opaque agents, lifecycle external. But no spatial metaphor, no human-as-avatar role.
- Nothing fuses them.

Closest MCP matches: `gesslar/lpc-mud-bridge-mcp` (1★ — one sandboxed assistant in one closed MUD), `Nexlen/mud-mcp` (32★ — single-player). A true shared persistent multi-participant world on-ramped via MCP: **zero results.** Related but different: Generative Agents / Smallville / Project Sid (closed sims), AutoGen / CrewAI / LangGraph (builder frameworks).

**Naming collision:** an unrelated 1990s "MCP" = *MUD Client Protocol* exists. Not Anthropic's Model Context Protocol.

**Reuse, don't rebuild:** MOO object semantics, FIPA performatives, A2A's pilot-owns-lifecycle stance, the MCP SDK, opencode as pilot. **Build (novel):** the open world + MCP as the single on-ramp normalizing humans/agents into equal avatars + talk-and-move suffices for everything, control included.

## Open questions

2. **Presence persistence & crash recovery** — should presence survive a restart/crash, and how to reconcile stale entries. Open question for future work.
3. **Auth & security model** — authentication, avatar identity, and malicious-agent defence on the network door. A dedicated topic for future work.
