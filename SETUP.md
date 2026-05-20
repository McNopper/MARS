# SETUP.md — Getting MARS running

A focused, step-by-step setup guide. For deeper build, server, and development topics see [BUILD.md](BUILD.md); for the service-agent catalogue see [AGENTS.md](AGENTS.md).

---

## 1. Prerequisites

### Required

| Requirement | Minimum version | Notes |
|-------------|-----------------|-------|
| Python | 3.11 | 3.12+ recommended |
| pip | 23+ | |
| git | 2.x | |
| Git LFS | any | required to pull `papers/` PDFs |

Verify:

```bash
python --version
pip --version
git --version
git lfs version
```

### Optional — only needed for specific providers

MARS starts and all tests run (skipping unavailable providers) without any of these.

| Tool | Why you need it | Install |
|------|----------------|---------|
| **GitHub CLI (`gh`)** | Copilot auth — `gh auth login` stores an OAuth token in a config file that MARS reads automatically (no `gh` on PATH needed after login) | [cli.github.com](https://cli.github.com) · `winget install GitHub.cli` · `brew install gh` |
| **Ollama** | Local LLM inference — free, no API key | [ollama.com/download](https://ollama.com/download) · `winget install Ollama.Ollama` · `brew install ollama` |
| **GitHub MCP server binary** | GitHub service agent — search repos, manage issues/PRs | Pre-bundled at `mars/runtime/agents/bin/github-mcp-server.exe`; see §5 below |

System tests check for each optional tool and **skip automatically** when it is not available:

```
tests/system/test_copilot_wire_agent.py   → skipped if gh auth login not done
tests/system/test_ollama_wire_agent.py    → skipped if Ollama not running
tests/system/test_multi_provider.py       → skipped if either Copilot or Ollama unavailable
```

---

## 2. Clone the repository

```bash
git clone https://github.com/McNopper/MARS
cd MARS
git lfs pull              # fetch research PDFs in papers/
```

---

## 3. Create a virtual environment (recommended)

```bash
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Linux / macOS
source .venv/bin/activate
```

---

## 4. Install MARS

### Core install

```bash
pip install -e ".[dev]"
```

This installs all runtime dependencies — LLM providers (OpenAI-compatible, Anthropic, Ollama, Copilot),
the SymPy symbolic math agent, the SciPy numerical math agent, and all other service agents.
All agents are auto-spawned when the server starts.

### Optional extras summary

| Extra | Packages added | Purpose |
|-------|---------------|---------|
| `dev` | pytest, pytest-asyncio | Run the test suite |
| `all` | all of the above | Full installation |

---

## 5. Configure provider credentials

```bash
cp .env.example .env
```

Open `.env` and fill in whichever provider settings you want to use.

### Anthropic / Claude — paid, requires API key

Anthropic Claude requires a paid API key. It uses the same CLI flags as the other providers but is not included in the default system tests (no free tier).

```env
# .env
ANTHROPIC_API_KEY=sk-ant-…             # ANTHROPIC_KEY is also accepted
```

Get a key at <https://console.anthropic.com> → **API Keys → Create Key**.

```bash
# Standalone CLI
python -m mars.client.cli.main --provider anthropic                                # default: claude-sonnet-4-6
python -m mars.client.cli.main --provider anthropic --model claude-opus-4-7        # adaptive thinking
python -m mars.client.cli.main --provider anthropic --model claude-haiku-4-5       # fastest tier

# Server: spawn one Anthropic agent on startup
python -m mars.runtime.server.main --provider anthropic

# Inside any CLI / TUI client
/spawn anthropic                                                            # alias: /spawn claude
/spawn anthropic claude-opus-4-7
```

Notes:

- The provider registers under `anthropic` with alias `claude` — both work.
- Extended-thinking models (`claude-opus-4-7`) automatically request adaptive
  thinking.
- Prompt caching can be enabled per-agent via `cache_prompts=True`.

### GitHub Copilot — free with a Copilot subscription

GitHub Copilot Chat API is available to anyone with a **GitHub Copilot Individual, Business, or Enterprise** subscription. There is no per-token cost beyond the subscription.

**Setup — one step:**

```bash
gh auth login
```

Follow the browser prompts. MARS calls `gh auth token` at startup to get the OAuth token automatically. That's it.

> Install `gh` if needed: `winget install GitHub.cli` (Windows) · `brew install gh` (macOS) · [cli.github.com](https://cli.github.com) (Linux)

**Start MARS with Copilot**

```bash
# Standalone CLI
python -m mars.client.cli.main --provider copilot                # default: gpt-4o
python -m mars.client.cli.main --provider copilot --model claude-3.7-sonnet

# Server
python -m mars.runtime.server.main --provider copilot

# Inside any CLI / TUI client
/spawn copilot
/spawn copilot gpt-4o-mini
```

Available models: `gpt-4o` (default), `gpt-4o-mini`, `o1-mini`, `claude-3.5-sonnet`, `claude-3.7-sonnet`.

### Local-only provider (no key, no cloud)

#### 🦙 Ollama — completely free, runs on your machine

Ollama serves open-weight models locally via an OpenAI-compatible API.
There are **no API keys, no rate limits, and no cloud dependency**.

**Install**

```bash
# Windows (winget)
winget install Ollama.Ollama

# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

Or download the installer directly from <https://ollama.com/download>.

**Pull a model**

```bash
ollama pull llama3.2          # 2 GB — fast, good quality (default for MARS)
ollama pull qwen2.5:7b        # 4.7 GB — strong multilingual model
ollama pull phi4              # 9 GB — Microsoft Phi-4, very capable
ollama pull deepseek-r1:8b    # 4.9 GB — reasoning model
```

> **Note:** Ollama model names are exact — `llama3.2`, `llama3.1`, `llama3.3` are
> all distinct. There is no bare `llama3` model unless you explicitly `ollama pull llama3`
> (which would fetch the legacy Llama 3 8B). MARS validates the model at spawn time and
> shows a `📦 Model not installed — Pull it with: ollama pull <name>` hint if you pick a
> name Ollama doesn't have.

**Start MARS with Ollama**

Ollama auto-starts its server on `http://localhost:11434` when you install it.

### GitHub MCP server — optional service agent

The GitHub MCP server gives LLM agents direct access to the GitHub API: search repos, read/write files, manage issues and PRs. It is **not auto-spawned** — use `/spawn github` when you need it.

**1. Download the binary**

Download the pre-built binary for your platform from the [releases page](https://github.com/github/github-mcp-server/releases/latest) and place it in the `bin/` directory at the project root (already gitignored):

```bash
# Create the bin/ directory if it doesn't exist
mkdir bin

# Download — replace the URL with the latest release for your platform:
# Windows x64
curl -L -o bin/github-mcp-server.zip \
  https://github.com/github/github-mcp-server/releases/latest/download/github-mcp-server_Windows_x86_64.zip
cd bin && unzip github-mcp-server.zip && cd ..

# Linux x64
curl -L https://github.com/github/github-mcp-server/releases/latest/download/github-mcp-server_Linux_x86_64.tar.gz \
  | tar -xz -C bin/

# macOS arm64
curl -L https://github.com/github/github-mcp-server/releases/latest/download/github-mcp-server_Darwin_arm64.tar.gz \
  | tar -xz -C bin/
```

Or with PowerShell (Windows):

```powershell
New-Item -ItemType Directory -Force bin
$url = (gh api repos/github/github-mcp-server/releases/latest --jq `
  '.assets[] | select(.name | contains("Windows_x86_64")) | .browser_download_url')
Invoke-WebRequest $url -OutFile bin\github-mcp-server.zip
Expand-Archive bin\github-mcp-server.zip bin\ -Force
```

**2. Set the active command in `agents.ini`**

The file already has the correct entry. On Linux/macOS, swap the active `command` line:

```ini
; Windows (default)
command = bin/github-mcp-server.exe stdio

; Linux / macOS — comment out the line above and uncomment this one:
;command = bin/github-mcp-server stdio
```

**3. Set credentials**

Add to `.env`:

```env
GITHUB_PERSONAL_ACCESS_TOKEN=gho_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Use the value from `gh auth token` (OAuth token) or a PAT with scopes `repo`, `read:org`, `read:user`.

**4. Spawn at runtime**

```
/spawn github
```

After spawning, any LLM agent in the room can call GitHub tools:

```
"Search for Python repos about multi-agent systems."
"Create an issue titled 'Fix login' in owner/repo."
"Read src/main.py from owner/repo on branch main."
```

---

## 6. Verify the installation

```bash
python -m pytest tests/ -x -q
```

Expected: check the output for the current test count.

Then run the offline mock CLI to confirm the runtime spins up:

```bash
python -m mars.client.cli.main --provider mock
```

Press `Ctrl-D` or type `/quit` to quit.

---

## 7. First real conversation

**With Ollama (free, local):**

```bash
python -m mars.client.cli.main --provider ollama
```

**With GitHub Copilot (subscription required, `gh auth login` once):**

```bash
python -m mars.client.cli.main --provider copilot
```

**Two providers at once — Ollama + Copilot:**

```bash
# Terminal 1: headless server
python -m mars.runtime.server.main

# Terminal 2: connect and spawn both
python -m mars.client.cli.main --remote localhost:7432
```

Inside the CLI:

```
/spawn ollama               # spawn a local Ollama agent
/spawn copilot gpt-4o-mini  # spawn a Copilot agent
/agents                     # list both agents
/switch <agent-id>          # direct messages to that agent
```

When the CLI is up, type any prompt at the input bar. Useful commands:

```
/agents available    list all service agents in the registry
/spawn <provider>    spawn an additional LLM agent
/help                full command list
```

---

## 8. Server / client mode

For multi-client setups, persistent agents, or sharing a single set of API keys across users, run MARS as a server with thin CLI clients connecting to it. The server owns all agents, credentials, and audit logs; clients are stateless terminals.

### Start the server

```bash
# Terminal 1 — headless server
python -m mars.runtime.server.main                            # uses defaults (no initial LLM agent)
python -m mars.runtime.server.main --provider ollama          # local Ollama (llama3.2, no API key)
python -m mars.runtime.server.main --provider ollama --model qwen2.5:7b  # different Ollama model
python -m mars.runtime.server.main --provider copilot         # GitHub Copilot (gh auth login once)
```

> A `mars-server` console script is also installed by `pip install -e ".[dev]"` — use it instead if your Python `Scripts/` (Windows) / `bin/` (Linux/macOS) directory is on `PATH`. The `python -m …` form always works regardless of `PATH`.

All free service agents auto-spawn from `mars/runtime/agents/agents.ini` on start:

| Agent | Skills | Requires |
|-------|--------|----------|
| `clock` | time, clock, location, geo, datetime | — |
| `profiler` | profiler, profile, performance, memory, cpu | — |
| `status` | status, protocol, introspection, runtime | — |
| `sympy` | math, solve, equation, sympy, algebra, calculus, … | — |
| `scipy` | scipy, numerical, quadrature, rootfind, optimize, linalg, stats, … | — |
| `file` | file, read, write, fileio, storage, filesystem, … | — |
| `url` | url, fetch, http, web, get, post, download, … | — |
| `ollama-models` | models, list-models, ollama-models, providers, tags | — |
| `launcher` | spawn_agent, launch, create_agent | — |
| `git` | git, diff, status, log, add, commit, branch, blame | gitpython (bundled) |
| `memory` | remember, recall, forget, memory_list, store_fact | — |
| `session` | save_session, load_session, list_sessions, session | — |

On-demand agents (not auto-spawned; use `/spawn <name>` to activate):

| Agent | Skills | Notes |
|-------|--------|-------|
| `shell` | shell, run, exec, bash, terminal | Runs with server privileges — activate only when needed |
| `scheduler` | schedule_after, schedule_every, after, every | Records schedules; auto-dispatch not yet wired |
| `github` | search_repositories, create_issue, list_pull_requests, … | Requires `GITHUB_PERSONAL_ACCESS_TOKEN` + binary |

Ports the server exposes:

| Port | Protocol | Purpose |
|------|----------|---------|
| 7432 | TCP (JSON-line) | CLI clients + service agents |
| 7433 | HTTP (REST) | `/agents`, `/spawn`, `/message`, `/scopes` |
| 7434 | WebSocket | Browser UI (same event protocol) |

### Start a client

```bash
# Terminal 2 — connect a CLI client
python -m mars.client.cli.main --remote                         # defaults to localhost:7432
python -m mars.client.cli.main --remote localhost:7432          # explicit host:port
python -m mars.client.cli.main --remote 192.168.1.10:7432       # remote server
```

> The equivalent console-script form is `mars --remote …` (also installed by `pip install -e ".[dev]"`).

Once connected, every `/spawn`, `/scope`, and `/message` runs on the server; multiple clients can share the same agents and scopes.

---

## 9. Troubleshooting

- **`/spawn github` fails with `No such file or directory`** — the `bin/github-mcp-server.exe` (Windows) or `bin/github-mcp-server` (Linux/macOS) binary is missing. Download it from [github-mcp-server releases](https://github.com/github/github-mcp-server/releases/latest) and place it in the `bin/` folder at the project root. See SETUP.md §5 for the exact steps.
- **`/spawn github` fails with `GITHUB_PERSONAL_ACCESS_TOKEN not set`** — add `GITHUB_PERSONAL_ACCESS_TOKEN=<token>` to `.env`. Use `gh auth token` to get the value.
- **`Copilot: no token found`** — no usable GitHub OAuth token was found. Run `gh auth login` (once). MARS reads the token directly from the gh CLI config file (`~/.config/gh/hosts.yml` on Linux/macOS, `%APPDATA%\GitHub CLI\hosts.yml` on Windows) — the `gh` CLI does not need to be on PATH after initial login. Alternatively, set `GITHUB_TOKEN=gho_…` in `.env`.
- **Personal Access Tokens (`ghp_…`) do not work** for Copilot — use `gh auth login` to get an OAuth (`gho_…`) token.
- **`ModuleNotFoundError: No module named 'openai'`** — MARS only needs `httpx` (already a core dependency) — no extra provider SDKs required. Reinstall with `pip install -e ".[dev]"` if your environment is incomplete.
- **`ModuleNotFoundError: No module named 'sympy'`** or **`No module named 'scipy'`** — reinstall with `pip install -e ".[dev]"` to get all dependencies.
- **Tests fail on import** — make sure you ran `pip install -e ".[dev]"` and are on Python 3.11+.
- **`papers/` PDFs look corrupt** — run `git lfs pull`.
- **Ollama `connection refused`** — Ollama server is not running; start it with `ollama serve` in a separate terminal.
- **`📦 Model 'X' is not installed in Ollama`** — you passed `--model X` but Ollama doesn't have it locally. Run `ollama list` to see what's installed, then either `ollama pull X` or pick one of the listed models. Note that `llama3` and `llama3.2` are different models — there is no bare `llama3` unless you explicitly pull it.

For deeper guidance (custom service agents, REST API, building a wheel, audit log, etc.) see [BUILD.md](BUILD.md).
