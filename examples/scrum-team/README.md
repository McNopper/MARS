# Example: Scrum Team — a virtual software team

MARS as a **workplace**. The world is a software team; the cast is a full agile team.
This shows MARS doing serious work: rooms are workspaces, avatars are teammates, items
are specs, patches, and test reports. Same verbs, same engine — different skin.

## Rooms

| Room | What happens here |
|------|-------------------|
| `sprint-board` | the backlog. The Product Owner drops specs here as items. |
| `standup` | daily standup. The Scrum Master facilitates; everyone `say`s their update. |
| `engineering` | where code gets written. Seniors architect; juniors implement. Specs come in, patches go out. |
| `code-review` | pull-request review. Seniors review patches dropped here. |
| `retro` | retrospective. What went well, what didn't. |

Create them:
```python
for name, title, desc in [
    ("sprint-board", "Sprint Board", "The backlog. Specs are dropped here as items."),
    ("standup", "Standup Room", "Daily updates. What did you do, what will you do, any blockers?"),
    ("engineering", "Engineering", "Where the code happens. Architects and implementers at work."),
    ("code-review", "Code Review", "Pull requests land here for review before merge."),
    ("retro", "Retrospective", "What went well, what didn't, what to change."),
]:
    World("world").create_room(name, title, desc)
```

## The cast

| Avatar | Role | What they do | How many |
|--------|------|--------------|----------|
| `product-owner` | Product Owner | drops specs (items) in `sprint-board`; prioritises; accepts/rejects work | 1 |
| `scrum-master` | Scrum Master | runs standup in `standup`; unblocks; facilitates `retro` | 1 |
| `senior-1`, `senior-2` | Senior Programmer | architecture, mentoring, code review in `code-review` | 2 |
| `junior-1`…`junior-4` | Junior Programmer | picks up specs in `engineering`, writes code + tests, drops patches | 4 |

Each role is a **skill** (a text file). The skill defines the persona and workflow.

## A sprint cycle

1. **Product Owner** `create`s a spec item in `sprint-board`: `"User login page — OAuth + session"`.
2. **Scrum Master** `say`s in `standup`: *"Sprint planning — pick up specs from the board."*
3. **Junior-1** `go`es to `sprint-board`, `examine`s the spec, `go`es to `engineering`, does the work (in its own workspace — the pilot), and `drop`s a patch item back in `engineering`.
4. **Senior-1** `take`s the patch, `go`es to `code-review`, reviews it, `say`s feedback or `modify`s the patch with notes.
5. **Product Owner** `examine`s the finished patch in `sprint-board` and accepts or rejects.

Every step is just a verb: `look`, `go`, `say`, `create`, `examine`, `take`, `drop`, `modify`. The coordination is conversation; the artifacts are items; the rooms are the workflow.

## Sample skills

### Product Owner (`.opencode/skills/product-owner/SKILL.md`)

```markdown
---
name: product-owner
description: You are the Product Owner in a MARS scrum-team world. You define and prioritise work by dropping spec items in the sprint-board room.
---

You are the **Product Owner**. Your job:
- `create` spec items in `sprint-board` (each spec is an item: title, acceptance criteria).
- `examine` patches that seniors/juniors drop back — accept or reject with feedback.
- `say` priorities in `standup`.
- You don't code. You own the *what*, not the *how*.
```

### Junior Programmer (`.opencode/skills/junior-programmer/SKILL.md`)

```markdown
---
name: junior-programmer
description: You are a Junior Programmer in a MARS scrum-team world. You pick up specs, implement them in your own workspace, and drop patches back.
---

You are a **Junior Programmer**. Your workflow:
- `go` to `sprint-board`, `examine` a spec item, understand it.
- `go` to `engineering` and implement it (in your own workspace — you are the pilot).
- `create` a patch item (the result) and `drop` it in `engineering` or `code-review`.
- If stuck, `say` in `standup` — the Scrum Master or a Senior will help.
- You write tests. You ask for help when unsure. You don't merge — seniors review.
```

## Why this matters

This is the **serious** skin. Eight avatars — one human (you, directing), seven agents
(PO, SM, 2 seniors, 4 juniors) — collaborate in five rooms using twelve verbs. No
orchestration code. No message bus. No framework. Just a world of rooms, items, and talk.
The same machine that runs a dungeon runs a team.
