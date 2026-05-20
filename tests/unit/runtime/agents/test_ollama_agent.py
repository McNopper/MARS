"""Unit tests for mars.runtime.agents.ollama_agent."""
from __future__ import annotations

import json

import pytest

from mars.runtime.agents import ollama_agent


class TestFormatSnapshot:
    def test_installed_names_listed(self) -> None:
        snap = {
            "host": "http://localhost:11434",
            "installed": [{"name": "llama3.2"}, {"name": "phi4"}],
            "running": [],
            "total_installed": 2,
            "total_running": 0,
        }
        out = ollama_agent._format_snapshot(snap)
        assert "llama3.2" in out
        assert "phi4" in out

    def test_running_names_listed(self) -> None:
        snap = {
            "host": "http://localhost:11434",
            "installed": [{"name": "llama3.2"}],
            "running": [{"name": "llama3.2"}],
            "total_installed": 1,
            "total_running": 1,
        }
        out = ollama_agent._format_snapshot(snap)
        assert "Running  (1)" in out

    def test_empty_shows_none(self) -> None:
        snap = {
            "host": "http://localhost:11434",
            "installed": [],
            "running": [],
            "total_installed": 0,
            "total_running": 0,
        }
        out = ollama_agent._format_snapshot(snap)
        assert "none" in out.lower()

    def test_host_shown(self) -> None:
        snap = {
            "host": "http://192.168.1.10:11434",
            "installed": [],
            "running": [],
            "total_installed": 0,
            "total_running": 0,
        }
        out = ollama_agent._format_snapshot(snap)
        assert "192.168.1.10:11434" in out


class TestFetchInstalled:
    def test_returns_error_on_connection_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            ollama_agent.urllib.request, "urlopen",
            lambda url, timeout=None: (_ for _ in ()).throw(OSError("refused")),
        )
        result = ollama_agent._fetch_installed("http://localhost:11434")
        assert len(result) == 1
        assert "error" in result[0]

    def test_parses_models_correctly(self, monkeypatch) -> None:
        class _Resp:
            def read(self):
                return json.dumps({"models": [
                    {"name": "llama3.2", "size": 2_000_000_000,
                     "details": {"family": "llama", "parameter_size": "3.2B",
                                 "quantization_level": "Q4_K_M"}},
                ]}).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass

        monkeypatch.setattr(
            ollama_agent.urllib.request, "urlopen",
            lambda url, timeout=None: _Resp(),
        )
        result = ollama_agent._fetch_installed("http://localhost:11434")
        assert len(result) == 1
        assert result[0]["name"] == "llama3.2"
        assert result[0]["family"] == "llama"
        assert result[0]["parameter_size"] == "3.2B"


class TestFetchRunning:
    def test_returns_empty_list_on_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            ollama_agent.urllib.request, "urlopen",
            lambda url, timeout=None: (_ for _ in ()).throw(OSError("refused")),
        )
        result = ollama_agent._fetch_running("http://localhost:11434")
        assert result == []

    def test_parses_running_models(self, monkeypatch) -> None:
        class _Resp:
            def read(self):
                return json.dumps({"models": [
                    {"name": "llama3.2", "size": 2_000_000_000},
                ]}).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass

        monkeypatch.setattr(
            ollama_agent.urllib.request, "urlopen",
            lambda url, timeout=None: _Resp(),
        )
        result = ollama_agent._fetch_running("http://localhost:11434")
        assert len(result) == 1
        assert result[0]["name"] == "llama3.2"
        assert result[0]["size_gb"] == pytest.approx(2.0, abs=0.1)
