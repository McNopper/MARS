# MARS — Planning & Roadmap

> The vision and principles live in [`README.md`](README.md). This is the **status**, the **roadmap**, and the **prior-art survey**.

## Vision in one paragraph

MARS is a multi-agent runtime expressed as a **world**: an open place where humans and AI agents meet as equal avatars in rooms and coordinate by talking. One door — **MCP** — and every actor walks through it. Any MCP-speaking agent is the pilot (opencode is the tested example); MARS ships no client and no LLM layer. The world is a directory of text files; `look`/`listen` read, `say` appends, `take`/`drop` move files.

## Status — Phase 0 done

A minimal, tested, **stable** world:

- `mars/world/world.py` — `World`: rooms + artifacts + inventories as plain text files (pure logic).
- `mars/world/server.py` — `WorldSession` (world + in-memory presence) wrapped as a FastMCP server. The single door.
- Verbs live: `look · listen · say · go · examine · take · drop · inventory · create · destroy · rooms`.
- Items: create / examine / take / drop / destroy; taking is exclusive (file-grounded atomic move).
- Rooms seeded (`lobby`, `library`); admin-authored via the engine / text files.
- opencode wiring: `opencode.jsonc` (the `mars` MCP server) + `.opencode/skills/mars-citizen/SKILL.md`.
- Tests: 42 unit + 1 end-to-end (drives the door as a real MCP client, marked `slow`).

The previous multi-agent **runtime** code (`mars/cli`, `mars/server`, `mars/common`) has been removed. MARS is now just the world.

## Model

- **A room is an abstract boundary** — a place, a sea, a chest, or an abstract context like a task. The **map** is just the outermost room. So a room *is* a context boundary.
- **Plain-text persistence** — no database; `world/` is `rooms/*.md` + `artifacts/<room>/` + `avatars/<avatar>/`. Durable state is text; only live presence is in memory.
- **One door (MCP), no parser** — natural language becomes tool calls inside the connecting agent, never inside MARS. opencode is the tested pilot; any MCP client works.

## Roadmap

The stable core (verbs, items, rooms, transports, in-session multi-avatar) is done — see **Status** above. Forward work, grouped by theme:

### Next — model completeness
- **Item kinds.** Today every item is portable. Add a *fixed* kind (a sign, a statue — can't be taken) and treat rooms as a *non-portable, enterable* kind. One `create` with a kind.
- **`create` makes rooms.** A "sea" is a room you create and enter but can't pick up — unify room and item authoring under one verb.
- **Ephemeral talk.** Spoken lines fade after a TTL (~60s); items stay durable. `listen` returns recent lines; old ones pruned. Talk is the transient layer; items are the record.
- **Items as real-document handles.** An item can point to a real file/URL; `examine` follows the link (the citizen fetches the paper, the spec, the contract it stands for).

### Then — the cast (multi-agent collaboration)
- **Example skills.** Ship `dm`, `coder`, `scientist` skills next to `mars-citizen`, so a new role is one copy away.
- **Persistent residents.** A daemon / always-on mode so a DM or specialist stays in the world between sessions (today's subagents are ephemeral — they finish and leave).
- **Cheap-router DM.** A DM avatar fields you on a free local model and escalates hard asks to a smarter avatar by talking to it — the human never picks models.
- **Async by default.** Make "leave a question; a specialist answers when it passes through" a deliberate, obvious pattern (it already works via the transcript).

### Later — scale & robustness
- **Context curation.** Summarise/compact a busy room's transcript so it stays within a context window.
- **Auth on the network door.** The SSE door is open today; add authentication for shared or public worlds.
- **Presence persistence / resume.** Optionally persist who's where, so a restart doesn't reset presence.
- **Observability.** An audit/log view of world events.

## Prior-art survey (does this already exist?)

**Verdict: the fusion does not exist.** Researched 2026-07-10 across the three MCP directories (official repo, Glama ~53.9k servers, mcp.so) plus the multi-agent-world landscape. Search engines were largely bot-blocked, so this rests on direct primary-source fetches — a quiet competitor could still appear, but as of now:

- **Spatial meeting-place** → MOO/MUD lineage (LambdaMOO): open, rooms, `take`/`drop`, humans as avatars. But it owns its character DB and has no LLM-native agent parity or MCP binding.
- **Open plug-in / pilot-owns-lifecycle** → A2A / MCP / FIPA ACL: opaque agents, lifecycle external. But no spatial metaphor, no human-as-avatar role.
- Nothing fuses them.

Closest MCP matches: `gesslar/lpc-mud-bridge-mcp` (1★ — one sandboxed assistant in one closed MUD), `Nexlen/mud-mcp` (32★ — single-player). A true shared persistent multi-participant world on-ramped via MCP: **zero results.** Related but different: Generative Agents / Smallville / Project Sid (closed sims), AutoGen / CrewAI / LangGraph (builder frameworks).

**Naming collision:** an unrelated 1990s "MCP" = *MUD Client Protocol* exists. Not Anthropic's Model Context Protocol.

**Reuse, don't rebuild:** MOO object semantics, FIPA performatives, A2A's pilot-owns-lifecycle stance, the MCP SDK, opencode as pilot. **Build (novel):** the open world + MCP as the single on-ramp normalizing humans/agents into equal avatars + talk-and-move suffices for everything, control included.

## Open questions

1. **Item kinds** — portable vs fixed vs room; how `create` expresses the kind.
2. **Real-document handles** — does an item embed content, link out, or both; how `examine` resolves a link.
3. **Persistent residents** — daemon mode vs separate connected instances for an always-on DM/specialist.
4. **Talk TTL** — default window for ephemeral talk; does anything besides talk decay?
5. **Auth model** — how to secure the network door for shared or public worlds.
