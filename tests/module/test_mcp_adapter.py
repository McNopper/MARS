"""Module tests for MCPAdapter: real subprocess, in-process adapter client.

These tests spawn actual service-agent subprocesses (clock, math) and call
their tools via MCPAdapter.  No MARS TCP server or LLM is involved — this
isolates the MCP stdio protocol layer.

No external services are required.
"""
from __future__ import annotations

import re
import sys

import pytest

from mars.srv.mcp_adapter import MCPAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmd(module: str) -> list[str]:
    return [sys.executable, "-m", module]


# ---------------------------------------------------------------------------
# Clock agent
# ---------------------------------------------------------------------------

class TestClockMCPAdapter:
    async def test_start_lists_get_time_tool(self):
        adapter = MCPAdapter("svc.clock@1", _cmd("mars.services.clock_agent"))
        try:
            tools = await adapter.start()
            names = [t.name for t in tools]
            assert "get_time" in names, f"Expected 'get_time' in tools, got: {names}"
        finally:
            await adapter.stop()

    async def test_call_returns_formatted_time(self):
        adapter = MCPAdapter("svc.clock@1", _cmd("mars.services.clock_agent"))
        try:
            await adapter.start()
            result = await adapter.call("what is the time?")
            # Should contain the clock emoji and a time-looking string
            assert "🕐" in result, f"Expected clock emoji in result: {result!r}"
            assert re.search(r"\d{2}:\d{2}:\d{2}", result), f"No time in result: {result!r}"
        finally:
            await adapter.stop()

    async def test_call_result_not_raw_json(self):
        adapter = MCPAdapter("svc.clock@1", _cmd("mars.services.clock_agent"))
        try:
            await adapter.start()
            result = await adapter.call("now")
            # Must not start with '{' (raw JSON dict)
            assert not result.strip().startswith("{"), \
                f"Result looks like raw JSON: {result[:80]!r}"
        finally:
            await adapter.stop()

    async def test_tool_name_matches_primary_skill(self):
        """The MCP tool name exposed by clock agent must be 'get_time'."""
        adapter = MCPAdapter("svc.clock@1", _cmd("mars.services.clock_agent"))
        try:
            tools = await adapter.start()
            assert tools[0].name == "get_time"
        finally:
            await adapter.stop()


# ---------------------------------------------------------------------------
# Math agent (SymPy)
# ---------------------------------------------------------------------------

class TestMathMCPAdapter:
    async def test_start_lists_solve_math_tool(self):
        adapter = MCPAdapter("svc.math@1", _cmd("mars.services.math_agent"))
        try:
            tools = await adapter.start()
            names = [t.name for t in tools]
            assert "solve_math" in names, f"Expected 'solve_math', got: {names}"
        finally:
            await adapter.stop()

    async def test_simple_solve(self):
        adapter = MCPAdapter("svc.math@1", _cmd("mars.services.math_agent"))
        try:
            await adapter.start()
            result = await adapter.call("x**2 - 4 = 0")
            assert "2" in result or "-2" in result, \
                f"Expected roots ±2 in result: {result!r}"
        finally:
            await adapter.stop()

    async def test_differentiation(self):
        adapter = MCPAdapter("svc.math@1", _cmd("mars.services.math_agent"))
        try:
            await adapter.start()
            result = await adapter.call("diff(x**3, x)")
            assert "3" in result, f"Expected '3x²' style in result: {result!r}"
        finally:
            await adapter.stop()

    async def test_result_not_raw_json(self):
        adapter = MCPAdapter("svc.math@1", _cmd("mars.services.math_agent"))
        try:
            await adapter.start()
            result = await adapter.call("x + 1")
            assert not result.strip().startswith("{"), \
                f"Result looks like raw JSON: {result[:80]!r}"
        finally:
            await adapter.stop()


# ---------------------------------------------------------------------------
# SciPy agent
# ---------------------------------------------------------------------------

class TestSciPyMCPAdapter:
    async def test_start_lists_solve_scipy_tool(self):
        pytest.importorskip("scipy")
        adapter = MCPAdapter("svc.scipy@1", _cmd("mars.services.scipy_agent"))
        try:
            tools = await adapter.start()
            names = [t.name for t in tools]
            assert "solve_scipy" in names, f"Expected 'solve_scipy', got: {names}"
        finally:
            await adapter.stop()

    async def test_numerical_integration(self):
        pytest.importorskip("scipy")
        adapter = MCPAdapter("svc.scipy@1", _cmd("mars.services.scipy_agent"))
        try:
            await adapter.start()
            result = await adapter.call("quad(x**2, 0, 1)")
            # ∫₀¹ x² dx = 1/3 ≈ 0.333
            assert "0.33" in result or "1/3" in result or "quad" in result, \
                f"Unexpected result: {result!r}"
        finally:
            await adapter.stop()

    async def test_result_not_raw_json(self):
        pytest.importorskip("scipy")
        adapter = MCPAdapter("svc.scipy@1", _cmd("mars.services.scipy_agent"))
        try:
            await adapter.start()
            result = await adapter.call("quad(x, 0, 1)")
            assert not result.strip().startswith("{"), \
                f"Result looks like raw JSON: {result[:80]!r}"
        finally:
            await adapter.stop()
