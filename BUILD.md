# BUILD.md — Building, testing, and packaging MARS

For installing and running the system, see **[SETUP.md](SETUP.md)**. For using the CLI, see **[USER.md](USER.md)**.

---

## Prerequisites

| Requirement | Minimum version |
|-------------|----------------|
| Python | 3.11 |
| pip | 23+ |
| git | any (2.x) |
| Git LFS | required for `papers/` PDFs |

---

## Editable install for development

```bash
git clone https://github.com/McNopper/MARS
cd MARS

# Install core dependencies + dev tools (pytest, pytest-asyncio)
pip install -e ".[dev]"
```

The current provider integrations only need `httpx` and the `anthropic` SDK (both core dependencies). `gitpython` is bundled for the git service agent. No other provider SDKs are required.

---

## Running tests

```bash
# All tests (excludes slow LLM provider tests)
python -m pytest tests/ -v

# A single test file
python -m pytest tests/unit/test_scope.py -v

# Quick green/red check
python -m pytest tests/ -x -q

# Include real-LLM provider tests (needs ANTHROPIC_API_KEY / Copilot / Ollama)
python -m pytest -m llm
```

Run `python -m pytest tests/ -x -q` and check the output for the current count (approximately 700 tests).

> Tests marked `@pytest.mark.llm` are excluded from the default run via `addopts = "-x -m 'not llm'"` in `pyproject.toml`. They require live API credentials and are intended for manual smoke-testing only.

### Test structure

Tests mirror the source tree exactly. Run the full suite with:

```bash
python -m pytest tests/ -x -q
```

**`tests/unit/`** — pure-Python, no I/O, no network

| Path | What it covers |
|------|---------------|
| `runtime/server/test_mcp_adapter.py` | MCPAdapter init, envelope constants |
| `runtime/agents/test_status_agent.py` | Status agent when REST is unreachable |
| `runtime/agents/test_launcher_agent.py` | Launcher `_parse_spawn_request` |
| `runtime/agents/test_shell_agent.py` | Shell agent dispatch, truncation, JSON form |
| `runtime/agents/test_git_agent.py` | Git agent dispatch, gitpython integration |
| `runtime/agents/test_memory_agent.py` | Memory agent CRUD, serialisation |
| `runtime/agents/test_session_agent.py` | Session save/load/list/rename/delete |
| `runtime/agents/test_scheduler_agent.py` | Scheduler after/every/cancel/list |
| `runtime/services/test_mcp_server.py` | MCPServer tool dispatch, `_to_content`, protocol |
| `runtime/services/test_service_utils.py` | Pure helpers: `parse_server`, `build_hello`, `encode_json_artifact`, `looks_like_base64`, etc. |
| `runtime/services/test_registry.py` | `_ServiceTool` name/description/parameters |
| `client/cli/test_tui_scroll.py` | TUI scroll buffer |
| `client/cli/test_sidebar_agents.py` | Sidebar agent list rendering |
| `client/cli/test_ui_bugs.py` | UI edge-case regression tests |
| `client/cli/test_cli_utils.py` | CLI utility helpers |
| `client/cli/test_cli_models.py` | CLI data models |
| `client/cli/test_cli_service_manager.py` | Service manager logic |
| `client/providers/test_provider_registry.py` | Provider registry lookup |
| `client/providers/test_copilot_provider.py` | Copilot token resolution (config file, env vars) |
| `client/providers/test_anthropic_provider_ext.py` | Anthropic provider extensions |
| `client/providers/test_anthropic_thinking.py` | Anthropic extended thinking |
| `storage/artifacts/test_artifacts.py` | Artifact store read/write |
| `storage/artifacts/test_artifact_store_observer.py` | Artifact observer notifications |
| `storage/artifacts/test_renderer_visual.py` | Renderer visual output |
| `storage/scopes/test_scope.py` | Scope creation and field validation |
| `storage/scopes/test_scope_store.py` | ScopeStore load / skill lookup |

**`tests/component/`** — single component with lightweight fakes

| Path | What it covers |
|------|---------------|
| `runtime/server/test_server.py` | Server message routing with fakes |

**`tests/module/`** — multi-component integration tests

| Path | What it covers |
|------|---------------|
| `runtime/server/test_mcp_adapter.py` | MCPAdapter subprocess lifecycle and tool calls |
| `runtime/server/test_external_mcp_spawn.py` | External MCP server spawn + tool routing |
| `runtime/services/test_registry.py` | INI-driven agent registry parsing and auto-spawn |
| `client/providers/test_providers.py` | MockProvider, base types, ToolSpec protocol |
| `storage/scopes/test_scopes.py` | Scope creation, store, domain contributions |

**`tests/system/`** — end-to-end with real TCP server and subprocesses

| Path | What it covers |
|------|---------------|
| `test_llm_wire_agent.py` | LLM wire agent full round-trip |
| `test_mcp_tool_call.py` | Internal MCP tool call round-trip |
| `test_external_mcp_tool_call.py` | External MCP server tool call end-to-end |
| `test_server_commands.py` | `/spawn`, `/switch`, `/join`, `/part`, `/list` command round-trips |
| `test_spawn_via_mcp_tool.py` | Agent-to-agent spawning via `launcher` MCP tool |
| `test_shell_agent_system.py` | Shell agent execution round-trip |
| `test_git_agent_system.py` | Git agent status/diff/log round-trip |
| `test_memory_agent_system.py` | Memory agent remember/recall/forget round-trip |
| `test_anthropic_wire_agent.py` | Anthropic wire agent integration (needs `ANTHROPIC_API_KEY`) |
| `test_copilot_wire_agent.py` | Copilot wire agent integration (needs Copilot subscription) |
| `test_ollama_wire_agent.py` | Ollama wire agent integration (needs local Ollama) |
| `test_multi_provider.py` | Copilot + Ollama together (marked `llm`, excluded from default run) |
| `test_cli_startup.py` | CLI startup and server connection |

> Tests marked `@pytest.mark.llm` make real LLM provider calls and are excluded from the default run. Run them explicitly with `python -m pytest -m llm`.

---

## Building a distributable wheel

```bash
pip install build
python -m build
# Produces dist/mars-<version>-py3-none-any.whl
# (<version> comes from the latest Git tag at build time)
```

---

## Git LFS (for research papers)

The `papers/` directory stores PDF research papers via Git Large File Storage:

```bash
# Install Git LFS (once per machine)
git lfs install

# After cloning, pull the actual PDFs
git lfs pull
```

All `*.pdf` files in the repo are tracked by LFS (see `.gitattributes`).

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'openai'`

MARS only needs `httpx` (already a core dependency) — no extra provider SDKs required.
If this appears, reinstall the project dependencies with `pip install -e ".[dev]"` in a fresh virtual environment.

### `asyncio.iscoroutinefunction` deprecation warning

Python 3.14 changed this API. Safe to ignore — will be resolved in a future release.
To suppress: `python -W ignore::DeprecationWarning -m mars.client.cli.main --provider mock`

### Tests fail on import

Make sure you installed in editable mode: `pip install -e ".[dev]"`
Check Python version: `python --version` (must be 3.11+).
