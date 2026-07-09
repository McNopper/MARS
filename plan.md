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
| `/model [name]` | Copilot CLI `/model` | Change the model on the current agent without stop + re-spawn. Sends a `ctrl set_model` wire frame to the wire agent. |

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
