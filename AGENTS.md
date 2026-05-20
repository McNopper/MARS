# 🌌 MARS Service Agent Catalogue

Built-in service agents are managed by the MARS server as **MCP stdio subprocesses** — the server launches them, feeds requests over stdin/stdout, and routes their replies to any participant that called the skill. They do **not** connect to `:7432` via TCP; no `--server` flag is needed.

Add custom agents to `mars/runtime/agents/agents.ini`; entries with `cost = free` are auto-spawned when the server starts.

---

## LLM providers vs. service agents

**You do not need a bridge agent or service agent to use Anthropic, GitHub Copilot, or Ollama.** These are first-class native providers. Spawn them directly:

```
/spawn anthropic                         → Claude Sonnet 4.6 (default)
/spawn anthropic claude-opus-4-7         → Claude Opus 4.7 with adaptive thinking
/spawn anthropic --thinking              → Claude with extended thinking enabled
/spawn copilot                           → GitHub Copilot Chat (gpt-4o)
/spawn ollama llama3.2                   → Local Ollama model
/spawn mock                              → Offline mock for testing
```

Each spawned agent is a full LLM wire agent that participates in rooms, skill routing, tool calls, and artifacts.

**Use a service agent when you need:**
- A specialised skill that is not an LLM (profiler, math, file I/O, sensor, hardware interface)
- Any non-conversational tool that takes a request and returns an artifact

---

## Built-in agents

### 🕐 Clock agent
Returns current time and node geolocation as a JSON artifact. Any agent can query it for a timestamp without needing direct network access.

- **Skills:** `get_time`, `time`, `clock`, `location`, `geo`, `datetime`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-clock`

### 📊 Profiler agent
Collects CPU, memory, and process statistics and returns a JSON artifact.

- **Skills:** `get_profile`, `profiler`, `profile`, `performance`, `memory`, `cpu`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-profiler`
- **Working dir:** `artifacts/profiler/`

### 🩺 Status agent
Exposes a runtime snapshot as a JSON artifact.

- **Skills:** `get_status`, `status`, `protocol`, `introspection`, `runtime`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-status --rest http://localhost:7433`

### 🚀 Launcher agent
Lets LLM agents spawn new agents by calling the `spawn_agent` tool.
Uses the `_mars_cmd` envelope — the MCP subprocess returns a structured JSON result that the server intercepts and executes. No direct TCP connection is needed.

**Removing the `[launcher]` entry from `agents.ini` disables agent-to-agent spawning.**
Human operators can always use `/spawn` from the CLI shell regardless.

- **Skills:** `spawn_agent`, `launch`, `create_agent`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-launcher`

---

## Science agents

SymPy and SciPy are included in the default install (`pip install -e .`).
Both agents are auto-spawned when the server starts.

### ∑ SymPy agent

Solves equations and evaluates symbolic expressions using [SymPy](https://www.sympy.org).

- **Skills:** `solve_math`, `math`, `solve`, `equation`, `sympy`, `algebra`, `calculus`, `integrate`, `differentiate`, `simplify`, `factor`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-sympy`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `x**2 - 4 = 0` | Solve for x (roots: ±2) |
| `solve(x**2 - 4, x)` | Explicit solve call |
| `diff(x**3, x)` | Symbolic differentiation → 3x² |
| `integrate(x**2, x)` | Indefinite integral → x³/3 |
| `integrate(x**2, (x, 0, 1))` | Definite integral → 1/3 |
| `integral of x**2` | Convenience form for indefinite integral |
| `limit(sin(x)/x, x, 0)` | Limit → 1 |
| `simplify(sin(x)**2 + cos(x)**2)` | Simplify → 1 |
| `expand((x+1)**3)` | Expand → x³+3x²+3x+1 |
| `factor(x**2 - 1)` | Factor → (x-1)(x+1) |

**Response fields:** `expression`, `operation`, `result`, `latex`, `numeric` (when applicable), `error`.

### 🔢 SciPy numerical math agent

Performs fast numerical computation using [SciPy](https://scipy.org).
Complements the SymPy agent: use SymPy for exact symbolic results, SciPy for
numerical root-finding, quadrature, optimisation, linear algebra, statistics, and ODEs.

- **Skills:** `solve_scipy`, `scipy`, `numerical`, `quadrature`, `rootfind`, `optimize`, `linalg`, `ode`, `statistics`, `stats`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-scipy`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `quad(x**2, 0, 1)` | Numerical integration ∫₀¹ x² dx → 0.333… |
| `dblquad(x*y, 0, 1, 0, 1)` | Double integration |
| `fsolve(x**2 - 4, 2.0)` | Root near x=2 → 2.0 |
| `brentq(x**2 - 4, 0, 3)` | Root in bracket [0,3] → 2.0 |
| `newton(x**2 - 4, 1.5)` | Newton/secant root → 2.0 |
| `minimize((x-3)**2, 0)` | Scalar optimisation → 3.0 |
| `minimize((x-2)**2+(y-3)**2, [0,0])` | 2-D optimisation |
| `solve([[1,2],[3,4]], [5,6])` | Linear system Ax=b |
| `det([[1,2],[3,4]])` | Determinant → -2.0 |
| `inv([[1,2],[3,4]])` | Matrix inverse |
| `eig([[1,2],[3,4]])` | Eigenvalues + eigenvectors |
| `lstsq([[1,1],[1,2],[1,3]], [1,2,3])` | Least squares |
| `norm.cdf(1.96)` | P(Z < 1.96) ≈ 0.975 |
| `norm.pdf(0, 0, 1)` | Standard normal PDF at 0 |
| `t.ppf(0.975, df=10)` | Student-t inverse CDF |
| `binom.pmf(3, n=10, p=0.5)` | Binomial PMF |
| `solve_ivp(dy=-y, t=[0,5], y0=[1.0])` | ODE dy/dt = −y |

**Response fields:** `operation`, `result`, `error`, `extra` (e.g. integration error estimate).

> **SymPy vs SciPy:** use `math`/SymPy when you need an exact symbolic answer
> (roots as fractions, LaTeX, algebraic manipulation). Use `scipy`/SciPy when you
> need a fast float answer, statistical distributions, matrix operations, or ODE integration.

---

## Development tool agents

### 🐚 Shell execution agent

Runs arbitrary shell commands and returns `stdout`, `stderr`, and `exit_code` as JSON.

⚠️ **Security:** the agent runs with the same privileges as the MARS server. It is `cost = demand` — use `/spawn shell` to activate it only when needed.

- **Skills:** `execute_shell`, `shell`, `run`, `exec`, `bash`, `command`, `terminal`
- **Cost:** demand (`/spawn shell`)
- **Spawn:** manual only
- **Standalone:** `mars-agent-shell`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `ls -la` | Run shell command in CWD |
| `pytest tests/ -x -q` | Run test suite |
| JSON: `{"cmd":"ls","cwd":"/tmp","timeout":10,"env":{"X":"1"}}` | Full options |

**Response fields:** `cmd`, `stdout`, `stderr`, `exit_code`, `ok`, `cwd`, `elapsed_s`, `error` (on OS error).
Output is truncated to 64 KB per stream.

---

### 🌿 Git agent

Git operations using **gitpython** — no `git` binary required on PATH beyond what gitpython needs.

- **Skills:** `git_diff`, `git_status`, `git_log`, `git_add`, `git_commit`, `git_branch`, `git_blame`, `git`, `diff`, `vcs`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-git`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `status` | `git status` in CWD |
| `diff` | `git diff` |
| `diff --staged` | `git diff --staged` |
| `log --oneline -10` | Recent commits |
| `blame src/main.py` | Per-line blame |
| `add .` | Stage all changes |
| `commit "Fix bug"` | Commit with message |
| `branch` | List branches |
| JSON: `{"op":"diff","args":["--staged"]}` | Structured form |

**Response fields:** `op`, `output`, `ok`, `error`.

---

### 🧠 Memory agent

Cross-session key-value memory persisted in `~/.mars/memory.json`.
LLM agents can remember facts across restarts and recall them in future sessions.

- **Skills:** `remember`, `recall`, `forget`, `memory_list`, `memory`, `store_fact`, `retrieve_fact`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-memory`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `remember project: MARS multi-agent platform` | Store fact under key `project` |
| `remember The user prefers dark mode` | Store fact with auto-generated key |
| `recall project` | Retrieve value for key `project` |
| `recall` | Return all stored facts |
| `forget project` | Delete a key |
| `forget all` | Clear all stored facts |
| JSON: `{"op":"remember","key":"x","value":"y"}` | Structured form |

**Response fields:** `op`, `key`, `value`, `ok`, `facts` (for `recall all`), `error`.

---

### 💾 Session agent

Saves and restores MARS conversations in `~/.mars/sessions/`. Sessions persist across server restarts and can be named, renamed, and shared.

- **Skills:** `save_session`, `load_session`, `list_sessions`, `rename_session`, `delete_session`, `session`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-session`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `save` | Save current session with a timestamp name |
| `save my-feature-work` | Save with a custom name |
| `list` | List all saved sessions |
| `load my-feature-work` | Restore a session |
| `rename my-feature-work refactor` | Rename a saved session |
| `delete old-session` | Delete a saved session |
| `info my-feature-work` | Show session metadata |
| JSON: `{"op":"save","name":"work"}` | Structured form |

**Response fields:** `op`, `name`, `ok`, `sessions` (for `list`), `metadata`, `error`.

---

### ⏰ Scheduler agent

Records one-shot and recurring prompt schedules in `~/.mars/schedules.json`.
Useful for timing reminders and to-do prompts.

> **Note:** The agent records schedules and returns IDs. Automatic prompt dispatch (polling and sending the prompt when due) is planned but not yet implemented — clients must poll `/list` and send due prompts manually for now.

- **Skills:** `schedule_after`, `schedule_every`, `cancel_schedule`, `list_schedules`, `scheduler`, `after`, `every`
- **Cost:** demand (`/spawn scheduler`)
- **Spawn:** manual only
- **Standalone:** `mars-agent-scheduler`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `after 30s run the tests` | Schedule one-shot prompt in 30 seconds |
| `after 5m check build status` | One-shot in 5 minutes |
| `every 10m ping me` | Recurring every 10 minutes |
| `cancel sched-abc12345` | Cancel a schedule by ID |
| `list` | List all pending schedules |
| JSON: `{"op":"after","delay":30,"prompt":"run tests"}` | Structured form |

**Response fields:** `op`, `id`, `delay_s`, `interval_s`, `prompt`, `ok`, `schedules` (for `list`), `error`.

---

## Data agents

### 📁 File I/O agent

Sandboxed file read/write/list/delete/mkdir inside `artifacts/fileio/`.
Path traversal (`..`) is blocked — agents cannot escape the sandbox.

- **Skills:** `file_io`, `file`, `read`, `write`, `fileio`, `storage`, `filesystem`, `list`, `delete`, `append`, `mkdir`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-file --workdir artifacts/fileio`

**Accepted request formats (the LLM extracts these from user messages):**

| Request | Operation |
|---------|-----------|
| `read notes.txt` | Read file contents |
| `write notes.txt Hello World` | Write (overwrite) a file |
| `append notes.txt More text` | Append to a file |
| `list ./` | List directory entries |
| `delete notes.txt` | Delete a file |
| `exists notes.txt` | Check if a file exists |
| `mkdir logs` | Create a directory |

JSON format is also accepted: `{"op":"write","path":"notes.txt","content":"Hello"}`.

### 🌐 URL fetch agent

HTTP GET/POST any public URL. Private/loopback IPs are blocked by default.

- **Skills:** `fetch_url`, `url`, `fetch`, `http`, `web`, `get`, `post`, `request`, `download`, `browse`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-url`

**Accepted request formats:**

| Request | Operation |
|---------|-----------|
| `https://example.com` | GET and return body |
| `fetch https://api.example.com/v1/data` | Explicit fetch keyword |
| JSON: `{"url":"…","method":"POST","body":"…"}` | POST with body |

**Security:** by default the agent blocks requests to `10.x`, `172.16.x`, `192.168.x`,
`127.x`, `169.254.x`, `::1`, `fc00::/7`. Pass `--allow-private` only in trusted networks.

### 🦙 Ollama models agent

Lists installed and running Ollama models as JSON.

- **Skills:** `list_ollama_models`, `models`, `list-models`, `ollama-models`, `providers`, `tags`
- **Cost:** free
- **Spawn:** auto-spawned on server start (MCP stdio)
- **Standalone:** `mars-agent-ollama`

### Echo renderer presets (`echo-text` / `echo-md` / `echo-void`)

Used to control how the CLI renders incoming replies.

| Preset | Behaviour |
|--------|-----------|
| `echo-text` | Plain text output |
| `echo-md` | Markdown-rendered output |
| `echo-void` | Discard (silent) |

Use `/echo <text|md|void>` to switch.

---

## Skill discovery

Every agent advertises its skills in the `hello` message. The server maintains a live
skill→agent_id index. Any participant can query it:

```json
{"t":"cmd","cmd":"list_skills"}
```

The server replies with a list of `{skill, agent_id, agent_type}` entries. To use a skill,
send a `msg` directly to the matching agent_id:

```json
{"t":"msg","target":"svc.sympy@1","text":"solve x**2 - 4 = 0"}
```

The service agent replies with a `msg` that the server routes back to the sender.

---

## Wire protocol

Built-in service agents use the **MCP stdio protocol** (JSON-RPC 2.0 over stdin/stdout).
The server's MCPAdapter manages the subprocess; LLM agents and humans never see this directly.

For advanced use cases that require a live TCP connection to the server (e.g. sending
server commands), a TCP wire agent can connect to `:7432` and use the protocol below.

### MCP stdio (recommended for new agents)

Register tools using the `MCPServer` decorator from `mars.runtime.services.mcp_server`:

```python
from mars.runtime.services.mcp_server import MCPServer
import asyncio

server = MCPServer("svc.myagent", "1.0.0")

@server.tool("my_tool", "Does something useful.")
def my_tool(request: str) -> str:
    return f"Result for: {request}"

asyncio.run(server.run())
```

The `@server.tool()` decorator accepts a name, description, and optional JSON Schema.
The tool function receives keyword arguments from the schema and returns a string (or dict/list, which is serialised to JSON).

#### `_mars_cmd` envelope

A tool can trigger a server-side action by returning a JSON object with `_mars_cmd`:

```python
import json

@server.tool("spawn_agent", "Spawn a new LLM agent.")
def spawn_agent(request: str) -> str:
    return json.dumps({
        "_mars_cmd": {"cmd": "spawn", "args": {"provider": "anthropic"}},
        "reply": "Spawning 'anthropic' — agent will appear shortly.",
    })
```

The server executes the command and routes `reply` to the caller. Currently supported
`_mars_cmd` values: `{"cmd": "spawn", "args": {"provider": "…", "model": "…"}}`.

### TCP wire protocol (advanced / legacy)

When direct server interaction is needed, connect via TCP to `:7432` and use
newline-delimited JSON frames.

#### `hello` — register the agent

```json
{"t":"hello","role":"agent","name":"my-agent","skills":["my-skill"]}
```

Optional: set `"agent_type":"ServiceAgent"` to control the icon in the UI.

#### `msg` — incoming request

```json
{"t":"msg","from":"cli-user@1","text":"analyse this data"}
```

#### `artifact` — return a binary or structured result

```json
{"t":"artifact","name":"result.json","mime":"application/json","data":"<base64>"}
```

---

## Agent types and icons

The CLI renders agents by `agent_type`:

| Icon | Type | Description |
|------|------|-------------|
| 🤖 | `LLMAgent` | LLM wire agent — Anthropic, GitHub Copilot, Ollama |
| 🔧 | `ServiceAgent` | Service agent — MCP stdio or TCP wire |
| 👤 | `HumanUser` | CLI terminal session |

---

## Adding a custom agent

Add a section to `mars/runtime/agents/agents.ini`:

```ini
[my-agent]
description = What my agent does
command = mars-agent-myagent
skills = my_primary_tool, my-skill, other-skill
category = service
cost = free
protocol = mcp
```

Then implement `mars-agent-myagent` using `MCPServer` (see above) and register it
in `pyproject.toml` as a console script. Restart the server to auto-spawn it.

For agents that need a direct TCP connection (rare), omit `protocol = mcp` and use
`{server}` in the command: `command = mars-agent-myagent --server {server}`.

---

## Integrating external MCP servers

Any third-party MCP server that runs as a **stdio subprocess** (the standard transport)
can be added to MARS without writing any Python code.

### How it works

When the server starts (or when `/spawn <name>` is issued), MARS:

1. Launches the external MCP process with its `command`
2. Performs the MCP `initialize` + `tools/list` handshake
3. Publishes every discovered tool — with its **real input schema** — to all LLM wire agents via a `spawn` event
4. Routes each LLM tool call as a structured `tools/call` JSON-RPC request, passing the full argument dict verbatim

This means multi-parameter tools (e.g. `search_repositories(q, page, per_page)`) work
correctly: the LLM sees the real schema and MARS forwards the structured arguments
without flattening them to a plain string.

### Adding an entry

```ini
[my-external-server]
description = Short description of what this server provides
command = npx -y some-mcp-package          # or: docker run -i --rm some/image
skills = primary_skill, secondary_skill    # used for skill routing + display
category = external
cost = demand                              # demand = /spawn only; free = auto-spawn
protocol = mcp
```

**`cost = demand`** means the server is not started automatically — use `/spawn my-external-server` at runtime.  
**`cost = free`** auto-starts it on every server launch (only use this for servers that need no credentials).

### Example: GitHub MCP server

The `[github]` entry is included in `agents.ini` (pre-configured, `cost = demand`).

**The binary is not shipped** — download it once and place it in `bin/` at the project root (gitignored). See [SETUP.md §5](SETUP.md) for platform-specific download instructions.

```ini
[github]
description = GitHub — search repos, read/write files, manage issues, PRs, and workflows
command = bin/github-mcp-server.exe stdio    ; Windows
;command = bin/github-mcp-server stdio       ; Linux / macOS
skills = search_repositories, get_file_contents, create_issue, list_issues, ...
category = external
cost = demand
protocol = mcp
```

**Prerequisites:**

| What | How |
|------|-----|
| Binary | Download from [github-mcp-server releases](https://github.com/github/github-mcp-server/releases/latest), place in `bin/` |
| Token | `GITHUB_PERSONAL_ACCESS_TOKEN` in `.env` — use `gh auth token` or a PAT with scopes `repo`, `read:org`, `read:user` |

**Usage:**

```
/spawn github
```

After spawning, the LLM can call any GitHub tool directly:

> *"Search for Python repos about multi-agent systems with more than 100 stars."*  
> *"Create an issue titled 'Fix login bug' in owner/repo."*  
> *"Read the contents of src/main.py from owner/repo on branch main."*

---

## Implementing a service agent

### Recommended: MCPServer decorator

```python
import asyncio
from mars.runtime.services.mcp_server import MCPServer

server = MCPServer("svc.myagent", "1.0.0")

@server.tool(
    "my_tool",
    "Short description of what this tool does.",
)
def my_tool(request: str) -> str:
    return f"processed: {request}"

def main():
    asyncio.run(server.run())

if __name__ == "__main__":
    main()
```

The handler may also be `async def`. For a custom input schema pass a JSON Schema
dict as the third argument to `@server.tool()`.

### TCP wire agent (advanced)

Use `service_utils.run_wire_agent` for agents that need persistent server connection:

```python
import asyncio
from typing import Any
from mars.runtime.services.service_utils import build_hello, run_wire_agent

def my_handler(text: str) -> dict[str, Any]:
    return {"result": f"processed: {text}"}

async def run_agent(server: str = "localhost:7432") -> None:
    await run_wire_agent(
        server,
        build_hello("svc.myagent", ["my-skill"]),
        my_handler,
        "my_result.json",
    )

if __name__ == "__main__":
    asyncio.run(run_agent())
```

`run_wire_agent` handles the TCP connection, `hello` registration, readline loop,
executor dispatch (sync handlers run in a thread pool), and graceful teardown.

### `service_utils` reference

| Helper | Signature | Description |
|--------|-----------|-------------|
| `build_hello` | `(name, skills) → dict` | Build a `hello` registration payload |
| `run_wire_agent` | `(server, hello, handler, artifact_name, …) → coro` | Full TCP event loop |
| `send_json` | `(writer, payload) → coro` | Write one JSON frame |
| `encode_json_artifact` | `(obj) → str` | Serialise to indented JSON → base64 ASCII |
| `has_module` | `(name) → bool` | Check if a package is installed |
| `parse_server` | `(server) → (host, port)` | Split `"host:port"` string |

