"""Unit tests for mars.runtime.agents.sympy_agent._strip_nl_prefix.

No SymPy installation required — only the regex helper is tested.
"""
from __future__ import annotations

import pytest

from mars.runtime.agents.sympy_agent import _strip_nl_prefix


@pytest.mark.parametrize("text, expected", [
    # plain math — untouched
    ("x**2 - 4", "x**2 - 4"),
    ("sin(x)", "sin(x)"),
    # single word prefixes
    ("calculate x**2", "x**2"),
    ("compute 3 + 4", "3 + 4"),
    ("evaluate sin(pi)", "sin(pi)"),
    ("find the roots", "the roots"),
    # "what is / what's"
    ("what is x**2 + 1?", "x**2 + 1"),
    ("what's sin(5)?", "sin(5)"),
    ("what are the roots of x**2-1?", "the roots of x**2-1"),
    # "please …"
    ("please calculate x**2 - 4", "x**2 - 4"),
    ("please evaluate sin(pi)", "sin(pi)"),
    ("please solve x**2 - 4 = 0", "x**2 - 4 = 0"),
    ("please simplify x**2 - 1", "x**2 - 1"),
    # "can you …"
    ("can you calculate x**2", "x**2"),
    ("can you solve x - 3 = 0", "x - 3 = 0"),
    # "could you …"
    ("could you simplify (x+1)**2", "(x+1)**2"),
    # "the value of"
    ("the value of sin(0)", "sin(0)"),
    ("the result of x**2 + 1", "x**2 + 1"),
    ("the answer to x - 5 = 0", "x - 5 = 0"),
    # stacked prefixes
    ("please calculate what is x**2 + 1?", "x**2 + 1"),
    # trailing punctuation stripped
    ("sin(x)?", "sin(x)"),
    ("x + 1,", "x + 1"),
])
def test_strip_nl_prefix(text: str, expected: str) -> None:
    assert _strip_nl_prefix(text) == expected
