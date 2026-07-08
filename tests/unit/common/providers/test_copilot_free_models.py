"""Unit tests for Copilot free/premium model classification.

Regression guard for the cost-reporting bug: GitHub Copilot bills premium-request
models (Claude, Gemini Pro, GPT-5, …) against a limited quota — they are NOT
free. Only the included GPT-4o / GPT-4.1 / GPT-3.5 family runs at no extra cost.
The catalogue and the unknown-model default must reflect that, otherwise MARS
under-reports cost and mis-picks "free" tiers.
"""
from __future__ import annotations

import pytest

from mars.server.services.llm.copilot import CopilotService

pytestmark = pytest.mark.unit


def test_included_base_models_are_free() -> None:
    for mid in ("gpt-4o", "gpt-4o-mini", "gpt-4.1"):
        assert CopilotService.KNOWN_MODELS[mid].is_free is True, mid


def test_premium_models_are_not_free() -> None:
    # Claude / Gemini are premium-request models on Copilot — must be paid.
    for mid in (
        "claude-sonnet-4.5", "claude-sonnet-4.6", "claude-haiku-4.5",
        "claude-opus-4.5", "claude-opus-4.8", "gemini-2.5-pro",
    ):
        assert CopilotService.KNOWN_MODELS[mid].is_free is False, mid


def test_stale_models_removed() -> None:
    # These were in the old curated list but are not served / were mis-flagged.
    for mid in ("claude-3.5-sonnet", "claude-3.7-sonnet"):
        assert mid not in CopilotService.KNOWN_MODELS, mid


@pytest.mark.parametrize(
    "model_id, included",
    [
        ("gpt-4o", True),
        ("gpt-4o-mini", True),
        ("gpt-4o-2024-11-20", True),
        ("gpt-4.1", True),
        ("gpt-4.1-2025-04-14", True),
        ("gpt-4", True),
        ("gpt-3.5-turbo", True),
        ("claude-opus-4.8", False),
        ("claude-sonnet-4.6", False),
        ("gemini-2.5-pro", False),
        ("gpt-5.5", False),
        ("gpt-5.4-mini", False),
        ("o1-mini", False),
    ],
)
def test_is_included_model_heuristic(model_id: str, included: bool) -> None:
    assert CopilotService._is_included_model(model_id) is included
