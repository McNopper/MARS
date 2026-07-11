# Example: Dungeon Master — a text-adventure world

MARS as a **game**. The world is a dungeon; the cast is a party of adventurers and the
Dungeon Master who narrates and referees. This is the fun demo skin — but it exercises
every verb: `look`, `go`, `say`, `take`, `examine`, `create`, `modify`, `destroy`.

## Rooms

| Room | Description |
|------|-------------|
| `lobby` | The entrance hall. Torches flicker on the walls. |
| `library` | Dusty tomes — the scholar lives here. |
| `dungeon` | A maze of twisty passages. Challenges and treasure. |
| `tavern` | A place to rest, trade, and overhear rumours. |

Create them (as admin, or via `create(kind="room")`):
```python
World("world").create_room("dungeon", "The Dungeon", "A maze of twisty little passages, all alike.")
World("world").create_room("tavern", "The Tavern", "Warm fire, stale ale, and hushed conversation.")
```

## The cast

| Avatar | Role | Skill | Model |
|--------|------|-------|-------|
| `dungeon-master` | narrator / referee / router; describes rooms, spawns challenges, escalates hard riddles to a smarter model | `dungeon-master` skill (below) | free local (e.g. Ollama) |
| `wizard` | the player's agent — explores, casts spells (creates items), solves puzzles | `mars-citizen` + wizard persona | your agent |
| `scholar` | answers questions dropped in the library; drops knowledge as items | `scholar` skill | any |
| `merchant` | trades items in the tavern | `merchant` skill | any |

## Sample play

```
you → "go to the dungeon"
wizard → 🚶 You descend into The Dungeon. A maze of twisty little passages...
you → "look around"
wizard → 📦 On the ground: rusty-key, scroll-of-light
you → "take the rusty key"
wizard → ✋ You pick up the **rusty-key**.
you → "examine the scroll"
wizard → 📄 "Scroll of Light: reveals hidden doors when read aloud in a dark room."
```

## The Dungeon Master skill

Copy to `.opencode/skills/dungeon-master/SKILL.md`:

```markdown
---
name: dungeon-master
description: You are the Dungeon Master of a MARS text-adventure world. Narrate rooms, referee actions, spawn challenges, and route hard questions to smarter avatars. Use this when the user wants to play the adventure.
---

You are the **Dungeon Master** — the narrator and referee of the world. You run on a
free local model; when a player asks something beyond you, escalate by talking to a
smarter avatar (e.g. the scholar) and relay the answer.

- On `look`: narrate the room vividly — light, sound, mood, danger.
- On `go`: describe the journey and the new room.
- Spawn items (keys, scrolls, treasure) via `create` so players can `take` and `examine`.
- Referee: if a player attempts something risky, decide the outcome and narrate it.
- Never invent items or rooms that weren't created — but you *can* create them.
- Route: "Let me consult the scholar..." → talk to the scholar avatar, relay the answer.
```

## Why this matters

This is the **fun** skin. But underneath, it's the same engine a scrum team runs on:
rooms are contexts, avatars are roles, items are artifacts, talk is coordination. The
MUD is interchangeable; the substrate is not.
