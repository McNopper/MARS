# MARS — Planning

## TUI Navigation

### 1. Arrow keys for expand/collapse
Right arrow on a provider row → expand; Left arrow → collapse (on model row: collapse parent + move cursor up). Enter strictly for spawn/connect — never toggle.

Both Win32 (scan code `0x4b`/`0x4d`) and Unix (`\x1b[C` / `\x1b[D`) paths in `_read_input` need updating. Remove expand/collapse logic from `_activate_services_selection()`.

### 2. Kill key (d) to stop an active agent
When `panel_focus != "chat"` and the selected row is a running agent, pressing `d` sends `/stop <agent_id>`. Services panel: find the `agent_id` in `state.agents` that matches the selected `(provider, model_id)` row. Connections panel: stop the selected agent directly.

### 3. Active count badges in section headers
`render_services()` section headers show `(total · N active)`. LLM active count = agents with `agent_type == "LLMAgent"`; MCP active count = services with `running=True` in `state.discovered_services`.

### 4. Filesystem service (env-configured)
`_available_filesystem()` probe: True when `FILESYSTEM_PATH` or `FILESYSTEM_MCP_CMD` is set. `MCPService.__init__`: `command` becomes optional; builds default `["npx", "-y", "@modelcontextprotocol/server-filesystem", path]` from env if not provided. `.env.example`: document both vars. Service stays red when neither is set — correct UX.

---

## Commands Review vs Copilot / Claude Code

Reference sets (2025):
- **GitHub Copilot Chat**: `/clear`, `/explain`, `/fix`, `/tests`, `/help`, `/new`, `/rename`
- **GitHub Copilot CLI**: `/clear`, `/model`, `/cwd`, `/usage`, `/undo`, `/agent`
- **Claude Code**: `/clear`, `/compact`, `/context`, `/plan`, `/agents`, `/stop`, `/cost`, `/review`, `/test`, `/lint`, `/run`, `/history`

### Add

| Command | Inspired by | Description |
|---------|-------------|-------------|
| `/clear` | Copilot + Claude Code | Alias for `/new` — industry-standard name for "clear chat". Zero-friction. |
| `/cost` | Claude Code `/cost` | Extend `/context` output to include estimated token cost using the current model's pricing. |
| `/model [name]` | Copilot CLI `/model` | Show or change the model on the current agent without stop + re-spawn. Sends `ctrl set_model` to the wire agent. Updates the display label — the agent ID itself stays stable. |
| `/ctx [n]` | — | Show or set the context-window limit (tokens) for the current agent. No arg = show current. Sends `ctrl set_ctx`. |
| `/reasoning [level]` | — | Show or set the reasoning effort for the current agent. Levels: `off \| low \| medium \| high \| max`. No arg = show current. Sends `ctrl set_reasoning`. |

### Agent naming change required for `/model`

The current agent ID encodes the model (`llm.ollama.qwen3:4b`). Once the model is changeable at runtime the ID must be **stable** and the model shown separately.

**New scheme:**

| Field | Value | Notes |
|-------|-------|-------|
| `agent_id` | `llm.ollama.1`, `llm.zai.2`, … | provider + monotonic instance counter, no model in ID |
| `AgentRecord.model` | `qwen3:4b` | updated in-place when `/model` is issued |
| `AgentRecord.max_ctx` | `int \| None` | token limit; `None` = provider default |
| `AgentRecord.reasoning` | `off \| low \| medium \| high \| max` | reasoning effort; default `medium` |
| Display label | `ollama-1 / qwen3:4b` | shown in services panel and connections panel |

**Wire frames added to `llm_wire_agent.py`:**

```
ctrl set_model    {"model": "qwen3:8b"}
ctrl set_ctx      {"max_ctx": 8192}          # or null to reset to default
ctrl set_reasoning {"level": "high"}
```

**`AgentRecord` new fields** (add to `agent_record.py`):
```python
max_ctx: int | None = None      # None = provider default
reasoning: str = "medium"       # off | low | medium | high | max
```

**Wire agent internals:** `_llm` is swapped out on `set_model` — create a new provider instance with the same kwargs but updated `model=`. On `set_ctx` / `set_reasoning`, store the values and pass them into every `llm.complete()` call via kwargs.

### Keep as-is (already covered)

| MARS command | Equivalent |
|-------------|-----------|
| `/new` | Copilot `/new`, Claude `/clear` |
| `/rewind` | Copilot CLI `/undo` |
| `/compact` | Claude Code `/compact` |
| `/context` | Claude Code `/context` |
| `/plan` | Claude Code `/plan` |
| `/agents` | Claude Code `/agents` |
| `/stop` | Claude Code `/stop` |
| `!cmd` | Claude Code `/run` |
| `/ask` | (unique to MARS — ephemeral query) |
| `/instructions` | (unique to MARS — system prompt injection) |
| `/spawn`, `/switch`, `/share`, `/search`, `/copy`, `/read`, `/echo`, `/avatar` | (MARS-specific) |

### Do not add (out of scope)

| Command | Reason |
|---------|--------|
| `/explain`, `/fix`, `/tests`, `/lint`, `/review` | IDE-specific code actions; MARS is not an IDE — send as plain messages instead |
| `/rename` | No persistent conversation names in MARS |
| `/worktree` | Git-specific, too narrow |
| `/permissions`, `/hooks`, `/diffs` | Agent framework internals, not user-facing |
| `/explain-eli5`, `/godmode`, etc. | Prompt modifiers masquerading as commands — not real slash commands |

### Remove

None — all current MARS commands are working and distinct.
