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

The current provider integrations only need `httpx`, which is already a core dependency.

---

## Running tests

```bash
# All tests
python -m pytest tests/ -v

# A single test file
python -m pytest tests/unit/test_scope.py -v

# Quick green/red check
python -m pytest tests/ -x -q
```

Run `python -m pytest tests/ -x -q` and check the output for the current count.

### Test files

**`tests/unit/`** — pure-Python, no I/O

| File | What it covers |
|------|---------------|
| `test_service_tool.py` | `_ServiceTool` name/description/parameters; launcher `_parse_spawn_request` |
| `test_scope.py` | Scope creation and field validation |
| `test_scope_store.py` | ScopeStore load / skill lookup |
| `test_tui_scroll.py` | TUI scroll buffer |
| `test_sidebar_agents.py` | Sidebar agent list rendering |
| `test_ui_bugs.py` | UI edge-case regression tests |
| `test_cli_utils.py` | CLI utility helpers |
| `test_cli_models.py` | CLI model listing |
| `test_cli_service_manager.py` | Service manager logic |
| `test_artifacts.py` | Artifact store read/write |
| `test_artifact_store_observer.py` | Artifact observer notifications |
| `test_renderer_visual.py` | Renderer visual output |
| `test_provider_registry.py` | Provider registry lookup |
| `test_anthropic_provider_ext.py` | Anthropic provider extensions |
| `test_anthropic_thinking.py` | Anthropic extended thinking |
| `test_status_agent_unreachable.py` | Status agent when REST is unreachable |

**`tests/component/`** — single component with fakes

| File | What it covers |
|------|---------------|
| (see directory) | Component-level tests with lightweight fakes |

**`tests/module/`** — multi-component module tests

| File | What it covers |
|------|---------------|
| `test_mcp_adapter.py` | MCPAdapter subprocess lifecycle and tool calls |
| `test_providers.py` | MockProvider, base types, ToolSpec protocol |
| `test_registry.py` | INI-driven agent registry parsing and auto-spawn |
| `test_scopes.py` | Scope creation, store, domain contributions |

**`tests/system/`** — end-to-end with real TCP server

| File | What it covers |
|------|---------------|
| `test_llm_wire_agent.py` | LLM wire agent full round-trip |
| `test_mcp_tool_call.py` | MCP tool call round-trip |
| `test_anthropic_wire_agent.py` | Anthropic wire agent integration |
| `test_copilot_wire_agent.py` | Copilot wire agent integration |
| `test_ollama_wire_agent.py` | Ollama wire agent integration |
| `test_cli_startup.py` | CLI startup and server connection |

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
To suppress: `python -W ignore::DeprecationWarning -m mars.cli.main --provider mock`

### Tests fail on import

Make sure you installed in editable mode: `pip install -e ".[dev]"`
Check Python version: `python --version` (must be 3.11+).
