# SETUP.md — Getting MARS running

A focused, step-by-step setup guide. For deeper build, server, and development topics see [BUILD.md](BUILD.md); for the service-agent catalogue see [AGENTS.md](AGENTS.md).

---

## 1. Prerequisites

| Requirement | Minimum version |
|-------------|-----------------|
| Python | 3.11 |
| pip | 23+ |
| git | 2.x |
| Git LFS | required to pull `papers/` PDFs |

Verify:

```bash
python --version
pip --version
git --version
git lfs version
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

### Core install (LLM agents + basic service agents)

```bash
pip install -e ".[dev]"
```

### With science agents (SymPy + SciPy math)

```bash
pip install -e ".[dev,science]"
```

This adds the **SymPy math agent** (symbolic algebra/calculus) and the **SciPy numerical agent**
(root-finding, integration, optimisation, statistics, linear algebra, ODEs).
Both are auto-spawned when the server starts if the packages are present.

### Install everything

```bash
pip install -e ".[all]"
```

Equivalent to `.[dev,anthropic,science]` — installs all optional dependencies at once.

### Optional extras summary

| Extra | Packages added | Purpose |
|-------|---------------|---------|
| `dev` | pytest, pytest-asyncio | Run the test suite |
| `anthropic` | anthropic ≥ 0.25 | Use Anthropic Claude models |
| `science` | sympy ≥ 1.12, scipy ≥ 1.12, numpy ≥ 1.26 | SymPy + SciPy math service agents |
| `all` | all of the above | Full installation |

---

## 5. Configure provider credentials

```bash
cp .env.example .env
```

Open `.env` and fill in whichever provider settings you want to use.

### Anthropic / Claude — paid, top-tier quality

Anthropic is the only **paid** provider currently shipped. Install the optional
SDK extra, set your API key, and you can chat with any current Claude model:

```bash
pip install -e ".[anthropic]"          # adds anthropic>=0.25 to the venv
```

```env
# .env
ANTHROPIC_API_KEY=sk-ant-…             # ANTHROPIC_KEY is also accepted
```

Get a key at <https://console.anthropic.com> → **API Keys → Create Key**.

```bash
# Standalone CLI
python -m mars.cli.main --provider anthropic                                # default: claude-sonnet-4-6
python -m mars.cli.main --provider anthropic --model claude-opus-4-7        # adaptive thinking
python -m mars.cli.main --provider anthropic --model claude-haiku-4-5       # fastest tier

# Server: spawn one Anthropic agent on startup
python -m mars.srv.main --provider anthropic

# Inside any CLI / TUI client
/spawn anthropic                                                            # alias: /spawn claude
/spawn anthropic claude-opus-4-7 --goal "Investigate flaky test" --behaviour proactive
```

Notes:

- The provider registers under `anthropic` with alias `claude` — both work.
- Extended-thinking models (`claude-opus-4-7`) automatically request adaptive
  thinking. For others you can opt in by passing `effort="low|medium|high"` to
  `AnthropicProvider` directly from Python.
- Prompt caching can be enabled per-agent via `cache_prompts=True`.

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

---

## 6. Verify the installation

```bash
python -m pytest tests/ -x -q
```

Expected: check the output for the current test count.

Then run the offline mock CLI to confirm the runtime spins up:

```bash
python -m mars.cli.main --provider mock
```

Press `Ctrl-D` or type `/quit` to quit.

---

## 7. First real conversation

```bash
python -m mars.cli.main --provider ollama
# or
python -m mars.cli.main --provider anthropic
```

When the CLI is up, type any prompt at the input bar to chat with the default agent. Useful commands:

```
/agents available    list all service agents in the registry
/spawn <provider>    spawn an additional LLM agent
/scope list          list domain scopes
/scope show <id>     display a scope document
/help                full command list
```

---

## 8. Server / client mode

For multi-client setups, persistent agents, or sharing a single set of API keys across users, run MARS as a server with thin CLI clients connecting to it. The server owns all agents, credentials, and audit logs; clients are stateless terminals.

### Start the server

```bash
# Terminal 1 — headless server
python -m mars.srv.main                            # uses defaults (no initial LLM agent)
python -m mars.srv.main --provider ollama          # local Ollama (llama3.2, no API key)
python -m mars.srv.main --provider ollama --model qwen2.5:7b  # different Ollama model
python -m mars.srv.main --provider anthropic       # Anthropic Claude
python -m mars.srv.main --password secret          # require a password from clients
```

> A `mars-server` console script is also installed by `pip install -e ".[dev]"` — use it instead if your Python `Scripts/` (Windows) / `bin/` (Linux/macOS) directory is on `PATH`. The `python -m …` form always works regardless of `PATH`.

All free service agents auto-spawn from `mars/services/agents.ini` on start:

| Agent | Skills | Requires |
|-------|--------|----------|
| `clock` | time, clock, location, geo, datetime | — |
| `profiler` | profiler, profile, performance, memory, cpu | — |
| `status` | status, protocol, introspection, runtime | — |
| `math` | math, solve, equation, sympy, algebra, calculus, … | `.[science]` |
| `scipy` | scipy, numerical, quadrature, rootfind, optimize, linalg, stats, … | `.[science]` |
| `file` | file, read, write, fileio, storage, filesystem, … | — |
| `url` | url, fetch, http, web, get, post, download, … | — |

The code executor is not auto-spawned — start it on demand with `/spawn code`.

Ports the server exposes:

| Port | Protocol | Purpose |
|------|----------|---------|
| 7432 | TCP (JSON-line) | CLI clients + service agents |
| 7433 | HTTP (REST) | `/agents`, `/spawn`, `/message`, `/scopes` |
| 7434 | WebSocket | Browser UI (same event protocol) |

### Start a client

```bash
# Terminal 2 — connect a CLI client
python -m mars.cli.main --remote                         # defaults to localhost:7432
python -m mars.cli.main --remote localhost:7432          # explicit host:port
python -m mars.cli.main --remote 192.168.1.10:7432       # remote server
python -m mars.cli.main --remote localhost --password secret
```

> The equivalent console-script form is `mars --remote …` (also installed by `pip install -e ".[dev]"`).

Once connected, every `/spawn`, `/scope`, and `/message` runs on the server; multiple clients can share the same agents and scopes.

---

## 9. Troubleshooting

- **`ModuleNotFoundError: No module named 'openai'`** — MARS only needs `httpx` (already a core dependency) — no extra provider SDKs required. Reinstall with `pip install -e ".[dev]"` if your environment is incomplete.
- **`ModuleNotFoundError: No module named 'sympy'`** or **`No module named 'scipy'`** — the SymPy/SciPy math agents need the `science` extra: `pip install -e ".[science]"`.
- **Tests fail on import** — make sure you ran `pip install -e ".[dev]"` and are on Python 3.11+.
- **`papers/` PDFs look corrupt** — run `git lfs pull`.
- **Ollama `connection refused`** — Ollama server is not running; start it with `ollama serve` in a separate terminal.
- **`📦 Model 'X' is not installed in Ollama`** — you passed `--model X` but Ollama doesn't have it locally. Run `ollama list` to see what's installed, then either `ollama pull X` or pick one of the listed models. Note that `llama3` and `llama3.2` are different models — there is no bare `llama3` unless you explicitly pull it.

For deeper guidance (custom service agents, REST API, building a wheel, audit log, etc.) see [BUILD.md](BUILD.md).
