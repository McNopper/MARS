"""Mock LLM provider – no API key required, works offline.

Generates realistic-looking responses for testing the full MARS TUI pipeline
without any external service. Simulates latency, tool calls, and multi-turn
conversation.

Usage
-----
    from mars.server.services.mock import MockProvider

    provider = MockProvider(delay=0.5)   # 0.5 s simulated latency
    provider = MockProvider(delay=0)     # instant replies

    # Fixed response (useful for unit tests)
    provider = MockProvider(response="Hello from mock!")
"""

from __future__ import annotations

import ast
import asyncio
import json
import operator
import re
from typing import Any

from mars.server.services.llm.base import LLMMessage, LLMProvider, LLMResponse, ModelInfo, ToolSpec

# ---------------------------------------------------------------------------
# Simple expression evaluator (safe subset: +  -  *  /  //  %  **  unary -)
# ---------------------------------------------------------------------------

_MATH_RE = re.compile(r"^\s*[\d\s\+\-\*\/\%\(\)\.\^]+\s*$")
_SAFE_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str) -> str | None:
    """Evaluate a simple arithmetic expression; return None if unsupported."""
    # Normalise ^ → **
    expr = expr.replace("^", "**")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return None

    def _eval(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            fn = _SAFE_OPS.get(type(node.op))
            if fn is None:
                raise ValueError("unsupported op")
            return fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            fn = _SAFE_OPS.get(type(node.op))
            if fn is None:
                raise ValueError("unsupported op")
            return fn(_eval(node.operand))
        raise ValueError("unsupported node")

    try:
        result = _eval(tree.body)
        # Pretty-print: drop trailing .0 for integers
        if result == int(result):
            return str(int(result))
        return str(round(result, 10))
    except Exception:
        return None


def _mock_reply(last_user: str) -> str | None:
    """Return a context-aware reply for simple factual questions, or None."""
    text = last_user.strip()
    # Strip MARS message prefix: "[From: cli-user]\n<actual text>"
    if "\n" in text:
        text = text.split("\n", 1)[-1].strip()

    # --- arithmetic ---
    # Look for patterns like "1 * 2", "what is 3+4?", "calculate 10/2"
    math_match = re.search(r"([\d\s\+\-\*\/\%\(\)\.\^]+)", text)
    if math_match:
        candidate = math_match.group(1).strip()
        if re.search(r"\d", candidate):
            result = _safe_eval(candidate)
            if result is not None:
                return f"**{candidate.strip()} = {result}**"

    return None


_RESPONSES = [
    "I've analysed your request. Based on the current agent state and the "
    "information available in the MARS platform, my recommendation is to proceed "
    "with a collaborative approach. Shall I coordinate with the other agents?",

    "Interesting problem. Let me think step by step:\n\n"
    "1. First, I'll gather the relevant data from the sensor agents.\n"
    "2. Then, I'll apply the negotiation strategy.\n"
    "3. Finally, I'll report back with a synthesised conclusion.\n\n"
    "Starting now…",

    "I've completed the analysis. Here's a summary:\n\n"
    "- **Status**: Nominal\n"
    "- **Confidence**: 94 %\n"
    "- **Next step**: await confirmation from domain expert agent\n\n"
    "Do you want me to proceed automatically?",

    "The build completed with 0 errors and 2 warnings. "
    "I'm reviewing them now and will apply fixes before the next iteration.",

    "Negotiation round 3: the counter-party accepted the revised proposal. "
    "Agreement reached on terms A and B; term C is still pending.",

    "Sensor data received: temperature 36.8 °C, humidity 42 %, CO₂ 412 ppm. "
    "All values within expected ranges. No anomalies detected.",

    "I found 3 agents matching your query in the directory:\n"
    "  • sensor-1 (SensorAgent, domain=sensors)\n"
    "  • gpt-agent (LLMAgent, domain=default)\n"
    "  • cli-user (CLIBridgeAgent, domain=cli)\n\n"
    "Which one do you want to contact?",
]


class MockService(LLMProvider):
    """Simulated LLM provider for offline / CI testing.

    Parameters
    ----------
    delay:
        Simulated response latency in seconds (default 0.8 s).
    response:
        If set, always returns this fixed string.  Useful for unit tests.
    vary:
        If True (default), pick a random response from the built-in bank.
    """

    provider_name = "mock"

    def __init__(
        self,
        delay: float = 0.8,
        response: str | None = None,
        vary: bool = True,
        model: str = "mock-1.0",
        **_: Any,
    ) -> None:
        self._delay = delay
        self._fixed = response
        self._vary  = vary
        self._model = model
        self._turn  = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **_: Any,
    ) -> LLMResponse:
        if self._delay > 0:
            await asyncio.sleep(self._delay)

        self._turn += 1

        if self._fixed is not None:
            text = self._fixed
        else:
            last = next(
                (m.content for m in reversed(messages) if m.role == "user"), ""
            )
            smart = _mock_reply(last)
            if smart is not None:
                text = smart
            elif self._vary:
                # Rotate through responses so multi-turn feels alive
                text = _RESPONSES[self._turn % len(_RESPONSES)]
            else:
                text = f"[mock] echo: {last}"

        return LLMResponse(
            content=text,
            tool_calls=[],
            finish_reason="stop",
            raw={"model": self._model, "turn": self._turn},
        )

    async def list_models(self) -> list[Any]:
        return [
            ModelInfo(
                id="mock-1.0",
                name="Mock LLM 1.0",
                description="Offline mock provider for testing",
                context_window=8192,
                is_free=True,
            )
        ]


class ToolCallMockService(LLMProvider):
    """Mock provider that emits a real tool call on the first turn.

    On turn 1: if *tools* is non-empty and the user message matches
    *trigger*, returns a tool-call for the best matching tool.
    On turn 2+: returns a natural-language reply that includes the
    tool result so tests can assert on it.

    Parameters
    ----------
    trigger:
        Substring (case-insensitive) in the last user message that
        activates tool calling (default: matches any message).
    tool_name:
        Force a specific tool by name; if None the first available tool
        is used.
    tool_request:
        The ``request`` argument forwarded to the tool.
    final_reply:
        Template for the final text reply.  ``{result}`` is substituted
        with the tool output.
    """

    provider_name = "mock"
    supports_tools = True

    def __init__(
        self,
        trigger: str = "",
        tool_name: str | None = None,
        tool_request: str = "now",
        final_reply: str = "The tool returned: {result}",
        delay: float = 0.0,
        **_: Any,
    ) -> None:
        self._trigger = trigger.lower()
        self._tool_name = tool_name
        self._tool_request = tool_request
        self._final_reply = final_reply
        self._delay = delay
        self._turn = 0
        self._model = "mock-tool-1.0"

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **_: Any,
    ) -> LLMResponse:
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        self._turn += 1

        last_user = next(
            (m.content or "" for m in reversed(messages) if m.role == "user"), ""
        )

        # Turn 1 with matching tools → emit a tool call
        if self._turn == 1 and tools:
            trigger_matches = (
                not self._trigger or self._trigger in last_user.lower()
            )
            if trigger_matches:
                tool = next((t for t in tools if t.name == self._tool_name), tools[0]) if self._tool_name else tools[0]
                tc_id = f"call_{tool.name}_1"
                return LLMResponse(
                    content=None,
                    tool_calls=[{
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "arguments": json.dumps({"request": self._tool_request}),
                        },
                    }],
                    finish_reason="tool_calls",
                )

        # Subsequent call → build reply from tool result in history
        tool_result = next(
            (m.content or "" for m in reversed(messages) if m.role == "tool"),
            None,
        )
        reply = self._final_reply.format(result=tool_result or "(no result)")
        return LLMResponse(content=reply, tool_calls=[], finish_reason="stop")

    async def list_models(self) -> list[Any]:
        return [ModelInfo(id="mock-tool-1.0", name="Mock Tool Provider", is_free=True)]
