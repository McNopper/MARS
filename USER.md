# 👤 Using MARS

A practical guide to the **MARS CLI** for day-to-day use: spawning agents, having conversations, sharing scopes, and exchanging artifacts.

For installation and server setup, see **[SETUP.md](SETUP.md)**. For internals, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Starting the CLI

### Standalone (auto-managed server)

Running `mars` without `--remote` automatically starts a local `mars-server` subprocess and
connects to it via TCP. All agents, service agents, and state live in that subprocess; the CLI
is a thin TCP client.

```bash
python -m mars.client.cli.main                                   # interactive; pick provider with /spawn
python -m mars.client.cli.main --provider mock                   # offline test agent, no key needed
python -m mars.client.cli.main --provider ollama                 # local Ollama — no API key, no limits 🦙
python -m mars.client.cli.main --provider copilot                # GitHub Copilot (needs gh auth login or GITHUB_TOKEN)
python -m mars.client.cli.main --provider anthropic --model claude-sonnet-4-6  # Anthropic Claude (needs ANTHROPIC_API_KEY / ANTHROPIC_KEY, or --key)
```

### Remote client (connect to an already-running server)

Use `--remote` to connect to an existing `mars-server`. The server owns all agents; the CLI is
just a terminal.

```bash
# In another terminal first, start the server:
python -m mars.runtime.server.main                            # echo bots only
python -m mars.runtime.server.main --provider ollama          # + local llama3.2 (unlimited, no key) 🦙

# Then connect from one or more CLI clients:
python -m mars.client.cli.main --remote                         # defaults to localhost:7432
python -m mars.client.cli.main --remote localhost:7432          # explicit host:port
python -m mars.client.cli.main --remote 192.168.1.10:7432       # remote server
```

The CLI opens with **four panels** arranged in a three-column layout:

| Column | Panels | Contents |
|--------|--------|----------|
| Left (top) | 🤖 **Agents** | Conversational agents: LLM, human, bridge |
| Left (bottom) | 🔧 **MCP Servers** | Service agents and the tools they expose |
| Centre | 💬 **Activity / Chat** | Message feed or active conversation |
| Right | 💬 **Rooms & Comms** | Group rooms and their members |

## Keyboard shortcuts

The four-pane TUI supports panel scrolling and focus switching with the keyboard.

| Key | Action |
|-----|--------|
| **Tab** | Cycle panel focus: Agents → Chat → Communications → Agents |
| **↑** / **↓** (Agents panel) | Move sidebar cursor — auto-switches the chat panel |
| **Mouse wheel** (Agents panel) | Same as ↑/↓ — scroll through agents |
| **PgUp** / **↑** (Chat panel) | Scroll up (older messages) |
| **PgDn** / **↓** (Chat panel) | Scroll down (newer messages) |
| **Enter** | Send message / confirm |
| **Backspace** | Delete last character |
| **Ctrl-C** | Exit |

The focused panel is highlighted with a **green** border. Moving the cursor in the Agents panel immediately switches the active agent in the chat panel — no `/switch` needed. A `►` marker highlights the selected agent. Sending a message or using `/switch` automatically scrolls the chat panel back to the newest message.

The **MCP Servers** panel (bottom-left) is read-only — it automatically lists every active service agent together with the tools it exposes. When a server has no tools yet (still initialising) it falls back to showing skill tags.

---

## Spawning agents

```text
/spawn mock                      # offline test agent, no key needed
/spawn ollama                    # local Ollama llama3.2 🦙
/spawn ollama phi4               # specific Ollama model
/spawn ollama phi4 --host http://192.168.1.10:11434   # remote Ollama
/spawn anthropic claude-sonnet-4-6            # Anthropic Claude (needs ANTHROPIC_API_KEY / ANTHROPIC_KEY)
/spawn copilot gpt-4o            # any registered provider + optional model
/spawn profiler                  # built-in service agent
/spawn status                    # built-in service agent
/spawn github                    # GitHub MCP server — needs GITHUB_TOKEN in .env and Docker or Node

# Role, goal, and behaviour flags (CrewAI / BDI conventions)
/spawn ollama --role "Code Reviewer" --goal "Review pull requests for quality and correctness"
/spawn ollama --role "Writer" --goal "Draft documentation" --behaviour proactive
```

Reactive agents show a `⚡` badge in the Agents panel and room member list. Proactive agents show `⏰` and emit periodic tick status events into their rooms.

`/providers` lists every registered backend; `/models <provider>` lists models for one. `/agents available` lists every spawnnable service agent from `mars/runtime/agents/agents.ini`.

## Autopilot agents

Goal-directed LLM agents run in **autopilot** when you give them a goal and proactive behaviour:

```text
/spawn ollama --goal "Draft the release summary" --behaviour proactive
/spawn anthropic claude-sonnet-4-6 --key sk-ant-... --goal "Monitor #research and coordinate specialists" --behaviour proactive
```

Each proactive tick feeds the goal back into the agent's own history so it can decide which tools to use next. For Python/API launches, set `tick_interval=30` (equivalent to a 30-second tick cadence) when constructing `LLMAgent`.

## Anthropic provider

Anthropic is registered as `anthropic` with alias `claude`, and defaults to `claude-sonnet-4-6`. Pass a key explicitly with `--key` or export `ANTHROPIC_API_KEY` / `ANTHROPIC_KEY`.

For Python/API usage, `AnthropicProvider` also supports:

- `thinking=True` + `thinking_budget=...` for manual extended thinking
- `effort="low|medium|high"` for adaptive thinking (`claude-opus-4-7` uses adaptive mode automatically)
- `cache_prompts=True` to mark the last system block for prompt caching

## Skill routing

Every service agent registers **skills** when it connects. LLM agents can discover
and invoke these skills using two built-in tools:

| Tool | What it does |
|------|-------------|
| `list_skills()` | Returns all skills available from service agents |
| `use_skill(skill, request)` | Invokes a skill and returns the result |

The LLM chooses the right tool automatically based on context. You can also call
skills explicitly when chatting with an agent:

> "Take a screenshot and describe what you see."  
> "What time is it and where are we located?"  
> "Show me the current CPU and memory usage."

MARS routes the request to the matching service agent, awaits its reply (message or
artifact), and returns the result to the LLM as a tool result — no manual agent IDs
or `/switch` needed.

---

## Visual mode badges

The CLI surfaces each agent's runtime mode directly in the UI:

- `⚡` — reactive agent (message-driven only)
- `⏰` — proactive agent (runs `on_tick()` on a schedule)

The badge appears in the **Agents** panel and in the room member list, so group chats show at a glance which participants may speak up on their own.

---

## Rooms & group chat

Every conversation happens inside a **room**. When you spawn an agent a room `#agent_id` is automatically created and you are placed in it. A 1:1 chat is just a room with one member — there is no special case.

```text
/list                            # list all active rooms and their members
/join #myroom                    # join (or create) a room
/part #myroom                    # leave a room (room auto-deleted when empty)
/switch #myroom                  # switch your active room
/switch agent_id                 # shorthand — switches to #agent_id room
```

**Group chat example** — four Ollama agents discussing in one room:

```text
/spawn ollama               # auto-creates #llm.ollama.llama3.2.1, joins you
/spawn ollama               # auto-creates #llm.ollama.llama3.2.2
/spawn ollama               # auto-creates #llm.ollama.llama3.2.3
/spawn ollama               # auto-creates #llm.ollama.llama3.2.4
/join #group                # create a shared room
/switch llm.ollama.llama3.2.1
/join #group
/switch llm.ollama.llama3.2.2
/join #group
/switch llm.ollama.llama3.2.3
/join #group
/switch llm.ollama.llama3.2.4
/join #group
/switch #group              # go back to the group room
Hello everyone!             # all four agents receive and can reply
```

The prompt shows `[#roomname GROUP]>` when you are inside a room.

---

## THINKING indicator

When an agent is processing a request, its tile in the **Agents** or **MCP Servers** panel shows an animated braille spinner (`⠋⠙⠹⠸…`) in blue. The spinner is driven by the system clock so it stays smooth at any refresh rate. When the reply is ready, the spinner is replaced by `✋ reply ready`.

---

## Message shortcuts

### `@file` — inline file context

Prefix a path with `@` anywhere in your message to expand the file's contents inline before sending:

```text
> Explain this function: @src/utils.py
> Review these changes: @diff.txt and tell me if they are safe
```

Multiple `@path` tokens in one message are all expanded. MARS warns and skips any path that cannot be read.

### `!cmd` — local shell shortcut

A message that starts with `!` runs the command locally in a subprocess and shows the output in the reply panel:

```text
!pytest tests/ -x -q
!git diff --staged
!ls -la
```

stdout and stderr are captured and displayed. The command runs with a 30-second timeout.

---

## Workspace commands

### `/new` — clear conversation

```text
/new
```

Clears the local conversation history display for the current agent. The agent's server-side state is not affected.

### `/compact` — summarise and compress

```text
/compact
```

Asks the current agent to summarise the entire conversation into a short paragraph, then replaces the displayed history with that summary. Useful when context is getting long.

### `/rewind` — undo last message pair

```text
/rewind
```

Removes the last user message and agent reply from the displayed history. Does not affect the agent's server-side memory.

### `/context` — token usage estimate

```text
/context
```

Prints a rough estimate of the current context window usage (characters ÷ 4 ≈ tokens).

### `/copy` — copy last reply to clipboard

```text
/copy
```

Copies the most recent agent reply to the system clipboard using `pyperclip` (install with `pip install "mars[clipboard]"`). Falls back to writing to a temporary file if pyperclip is not installed.

### `/share` — export conversation

```text
/share                   # save to ./mars-chat-YYYYMMDD-HHMMSS.md
/share ./review.md       # save to a specific path
```

Exports the full conversation log for the current agent to a Markdown file.

### `/search` — search history

```text
/search <query>
```

Filters the activity feed to show only messages that contain `<query>`.

### `/ask` — ephemeral side question

```text
/ask What does RFC 9110 say about ETags?
```

Sends a one-off question to the current agent. The exchange is flagged as ephemeral — it is sent and displayed but does not permanently modify your main conversation thread.

### `/plan` — request an implementation plan

```text
/plan Add pagination support to the user list endpoint
```

Sends the task description to the current agent with an instruction to think step-by-step and produce an implementation plan before writing any code.

### `/instructions` — load project rules

```text
/instructions
```

Looks for a project instructions file in the current directory (searches for `AGENTS.md`, `CLAUDE.md`, `copilot-instructions.md`, `.github/copilot-instructions.md` in order). If found, the file's contents are sent to the current agent as a system-level instruction that applies to all subsequent replies.

### `/theme` — switch colour theme

```text
/theme             # list available themes
/theme dark        # switch to dark theme
/theme light       # switch to light theme
```

### `/version` — show MARS version

```text
/version
```

---



Anything that does **not** start with `/` is sent as a message to the **current room** (shown in the prompt). All members of the room — agents and humans — receive the message.

```text
> what is the capital of France?
```

Switch rooms with `/switch <agent_id>` or `/switch #roomname`. Read a pending reply with `/read`, or toggle auto-printing with `/verbose`.

State and strategy:

```text
/status               # show FSM state of current agent
```

### Chat renderer (`/echo`)

Incoming agent replies are rendered through whichever echo mode is active:

```text
/echo            # show current mode
/echo text       # plain text (no markdown)
/echo md         # rich markdown (default)
/echo void       # silently discard incoming replies
```

The matching service agents `echo-text`, `echo-md`, and `echo-void` are
auto-spawned on server start; `/echo` only flips the client-side renderer
and never sends a message.

---

## Provider errors & rate limits

When a cloud provider's quota is exhausted or the API call fails, the agent replies
with an emoji message in the chat pane — **no crash, no silent hang**:

| Emoji | Meaning |
|-------|---------|
| 🚫 **Rate limit reached.** | Free-tier quota exhausted (e.g. GitHub Models per-minute limit). Wait ~1 min and try again, or switch to Ollama. |
| ⚠️ **Provider error** | Unexpected API error (network issue, bad model name, etc.). |

**To avoid rate limits entirely**, use Ollama — completely free, runs locally, no quotas:

```bash
python -m mars.runtime.server.main --provider ollama   # server mode
python -m mars.client.cli.main --provider ollama   # standalone
```

See [SETUP.md](SETUP.md) for the full Ollama install guide.

---

## Avatars & cosmetics

```text
/avatar                          # show the avatar gallery
/avatar 3                        # pick avatar #3
/avatar 🦊                        # or set a custom emoji
```

---

## Cheat sheet

| Command | What it does |
|---------|-------------|
| `/spawn <provider> [model]` | Spawn a new LLM agent (auto-creates `#agent_id` and adds the agent to it) |
| `/spawn … --role <r> --goal <g>` | Assign CrewAI-style role + goal (prepended to system prompt) |
| `/spawn … --behaviour reactive\|proactive` | Choose the runtime mode; badges show `⚡` or `⏰` in the UI |
| `/stop <agent_id>` | Stop and despawn an agent |
| `/agents` / `/agents available` | List active / spawnnable agents |
| `/switch <agent_id\|#room>` | Change current room |
| `/list` | List all active rooms and members |
| `/join #room` | Join (or create) a room |
| `/part #room` | Leave a room |
| `/read [agent_id]` | Read pending reply |
| `/verbose [agent_id]` | Toggle auto-print |
| `/status [agent_id]` | Show FSM state + strategy |
| `/echo <text\|md\|void>` | Select chat renderer (plain / markdown / discard) |
| `/new` | Clear conversation history display |
| `/compact` | Summarise and compress conversation |
| `/rewind` | Undo last user+agent message pair |
| `/ask <question>` | Ephemeral side question (not saved to history) |
| `/plan <task>` | Request an implementation plan |
| `/context` | Show token usage estimate for current context |
| `/copy` | Copy last reply to clipboard |
| `/share [path]` | Export conversation to a Markdown file |
| `/search <query>` | Search conversation history |
| `/instructions` | Load project instructions (AGENTS.md / CLAUDE.md / …) |
| `/theme [name]` | Switch colour theme |
| `/version` | Show installed MARS version |
| `/help` | Full help text |
| `/quit` or Ctrl-D | Quit |
| `@path` in message | Expand file contents inline before sending |
| `!cmd` as message | Run a local shell command; show output in the reply panel |
