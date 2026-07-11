# AGENTS.md — MARS

This repository is **MARS**, an open world where humans and AI agents meet as equal
avatars in rooms and coordinate by talking. See [`README.md`](README.md) for the full
vision and [`plan.md`](plan.md) for the roadmap.

## Entering the world

The MARS world is wired up as a local MCP server (`opencode.jsonc` → `mars`). Its entire
surface is a small set of verbs: `look`, `listen`, `say`, `go`, `examine`, `take`,
`drop`, `inventory`, `create`, `append`, `destroy`, `rooms`.

To explore the world as a citizen, load the **`mars-citizen`** skill, then ask to look
around. The world is a directory of text files under `world/` (auto-created on first run).

## Working on MARS itself

The world server is small and lives in `mars/world/`:

- `mars/world/world.py` — `World`: durable state as text files (rooms, artifacts, inventories). Pure logic, no MCP.
- `mars/world/server.py` — `WorldSession` (world + in-memory presence) wrapped as a FastMCP server. The single door.

Run the server directly: `python -m mars.world.server --world-dir world`.

### Tests

The world engine is unit-tested; the MCP door has an end-to-end test that drives it as a
real MCP client (spawns a subprocess, so it is marked `slow` and excluded from the default run).

- Default suite: `python -m pytest`
- Including the end-to-end MCP test: `python -m pytest -m slow --override-ini="addopts="`

### Conventions

- The world is **plain text only** — no database. New persistent state becomes a file under `world/`.
- Durable state = text files; only live presence (who is in which room) is in memory.
- There is **one door** (MCP) and **no parser** — natural language becomes tool calls inside the connecting agent, never inside MARS.
