"""Unit tests for mars.runtime.agents.profiler_agent."""
from __future__ import annotations

import pytest

from mars.runtime.agents import profiler_agent


class TestCollectStats:
    def test_required_keys(self) -> None:
        stats = profiler_agent.collect_stats()
        for key in ("timestamp", "pid", "platform", "python", "cpu_count",
                    "process_time_seconds"):
            assert key in stats, f"missing key: {key}"

    def test_pid_is_integer(self) -> None:
        import os
        stats = profiler_agent.collect_stats()
        assert stats["pid"] == os.getpid()

    def test_cpu_count_positive(self) -> None:
        stats = profiler_agent.collect_stats()
        assert isinstance(stats["cpu_count"], int)
        assert stats["cpu_count"] >= 1

    def test_process_time_non_negative(self) -> None:
        stats = profiler_agent.collect_stats()
        assert stats["process_time_seconds"] >= 0.0


class TestFormatStats:
    def _base_stats(self) -> dict:
        return {
            "platform": "Linux-5.15",
            "pid": 1234,
            "python": "3.12.0",
            "cpu_count": 8,
            "cpu_percent": 42.5,
            "rss_bytes": 52_428_800,   # 50 MB
            "memory_percent": 1.2,
            "load_average": [0.5, 0.7, 0.9],
        }

    def test_contains_pid(self) -> None:
        out = profiler_agent._format_stats(self._base_stats())
        assert "1234" in out

    def test_contains_rss_mb(self) -> None:
        out = profiler_agent._format_stats(self._base_stats())
        assert "50.0 MB" in out

    def test_contains_cpu_percent(self) -> None:
        out = profiler_agent._format_stats(self._base_stats())
        assert "42.5%" in out

    def test_none_rss_shows_na(self) -> None:
        stats = self._base_stats()
        stats["rss_bytes"] = None
        out = profiler_agent._format_stats(stats)
        assert "n/a" in out

    def test_none_cpu_shows_na(self) -> None:
        stats = self._base_stats()
        stats["cpu_percent"] = None
        out = profiler_agent._format_stats(stats)
        assert "n/a" in out

    def test_none_load_shows_na(self) -> None:
        stats = self._base_stats()
        stats["load_average"] = None
        out = profiler_agent._format_stats(stats)
        assert "n/a" in out
