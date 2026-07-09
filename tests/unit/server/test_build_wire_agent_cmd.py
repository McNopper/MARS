"""Unit tests for the unified LLM wire-agent command builder.

``MARSServer._build_wire_agent_cmd`` is the single source of truth used by
``/spawn``, the ``_mars_cmd`` envelope, and the startup auto-spawn.
"""
from __future__ import annotations

from mars.server.main import MARSServer


def _opt(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def test_plain_provider() -> None:
    cmd = MARSServer._build_wire_agent_cmd("host:7432", provider="ollama")
    assert "--provider" in cmd and _opt(cmd, "--provider") == "ollama"
    assert _opt(cmd, "--server") == "host:7432"
    # No knobs requested → none present.
    for flag in ("--thinking", "--cache-prompts", "--no-cache-prompts", "--skills", "--max-tokens"):
        assert flag not in cmd


def test_provider_slash_model_split() -> None:
    cmd = MARSServer._build_wire_agent_cmd("h:1", provider="ollama/qwen3:4b")
    assert _opt(cmd, "--provider") == "ollama"
    assert _opt(cmd, "--model") == "qwen3:4b"


def test_explicit_model_overrides_provider_suffix() -> None:
    cmd = MARSServer._build_wire_agent_cmd(
        "h:1", provider="ollama/qwen3:4b", model="llama3.2"
    )
    assert _opt(cmd, "--model") == "llama3.2"


def test_knobs_appended() -> None:
    cmd = MARSServer._build_wire_agent_cmd(
        "h:1",
        provider="ollama",
        model="qwen3:4b",
        thinking=True,
        cache_prompts=True,
        max_tokens=16000,
        skills=["store_artifact", "complete_phase"],
    )
    assert "--thinking" in cmd
    assert "--cache-prompts" in cmd
    assert _opt(cmd, "--max-tokens") == "16000"
    assert _opt(cmd, "--skills") == "store_artifact,complete_phase"


def test_cache_prompts_false_emits_negation() -> None:
    cmd = MARSServer._build_wire_agent_cmd("h:1", provider="ollama", cache_prompts=False)
    assert "--no-cache-prompts" in cmd
    assert "--cache-prompts" not in cmd


def test_skills_string_passthrough() -> None:
    cmd = MARSServer._build_wire_agent_cmd("h:1", provider="ollama", skills="a,b,c")
    assert _opt(cmd, "--skills") == "a,b,c"
