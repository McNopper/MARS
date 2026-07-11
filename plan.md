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

### Next — model refinements

- **Portable vs fixed items.** Today every item can be taken. Add a *fixed* kind that cannot be picked up (a sign on the wall, a statue). Rooms are inherently non-portable (you enter them, you don't carry them).
- **`create` makes rooms too.** A "sea" is just a room you create and enter but can't pick up — unify room/item authoring under `create` with a kind, so a citizen can spawn a new context (room) as easily as a note.
- **Ephemeral talk.** Spoken lines fade after a TTL (default ~60s) — talk is transient, items are the durable record. `listen` returns only recent lines; old ones pruned. (Confirm: only talk decays, not items.)

### Then — multi-avatar (the cast comes alive)

Already proven: subagents within one opencode session share the server's live presence — a `wizard` and a `scholar` met an `explorer` in the lobby and held a Q&A. What remains:

- **Persistent residents.** opencode `Task` subagents are ephemeral (they finish and leave). For an always-on **DM** or **specialists** you can drop in on, run separate connected agent instances against the same world (e.g. via the SSE network door) — then they're real citizens you converse with any time.
- **Cheap-router DM.** A DM avatar fields you on a free local model and escalates hard asks to a smarter avatar by talking to it — so the human never picks models.

## Prior-art survey (does this already exist?)

**Verdict: the fusion does not exist.** Researched 2026-07-10 across the three MCP directories (official repo, Glama ~53.9k servers, mcp.so) plus the multi-agent-world landscape. Search engines were largely bot-blocked, so this rests on direct primary-source fetches — a quiet competitor could still appear, but as of now:

- **Spatial meeting-place** → MOO/MUD lineage (LambdaMOO): open, rooms, `take`/`drop`, humans as avatars. But it owns its character DB and has no LLM-native agent parity or MCP binding.
- **Open plug-in / pilot-owns-lifecycle** → A2A / MCP / FIPA ACL: opaque agents, lifecycle external. But no spatial metaphor, no human-as-avatar role.
- Nothing fuses them.

Closest MCP matches: `gesslar/lpc-mud-bridge-mcp` (1★ — one sandboxed assistant in one closed MUD), `Nexlen/mud-mcp` (32★ — single-player). A true shared persistent multi-participant world on-ramped via MCP: **zero results.** Related but different: Generative Agents / Smallville / Project Sid (closed sims), AutoGen / CrewAI / LangGraph (builder frameworks).

**Naming collision:** an unrelated 1990s "MCP" = *MUD Client Protocol* exists. Not Anthropic's Model Context Protocol.

**Reuse, don't rebuild:** MOO object semantics, FIPA performatives, A2A's pilot-owns-lifecycle stance, the MCP SDK, opencode as pilot. **Build (novel):** the open world + MCP as the single on-ramp normalizing humans/agents into equal avatars + talk-and-move suffices for everything, control included.

## Open questions

1. **Persistent residents** — how to keep a DM/specialist always-on (separate connected instances, or a daemon mode) so they're citizens you can drop in on.
2. **Item kinds** — portable vs fixed vs room; how `create` expresses the kind.
3. **Talk TTL** — default window for ephemeral talk, and whether anything besides talk decays.
