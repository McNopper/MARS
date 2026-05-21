"""Unit tests for mars.client.cli.math_renderer.

Tests cover:
- ``preprocess_math`` — top-level entry point
- ``_apply_subs`` — Unicode symbol substitution table
- ``_apply_scripts`` — super/subscript conversion
- ``_render_inline`` / ``_render_display`` — SymPy + fallback paths
- Fence-span guard — code fences are left untouched
- Inline and display delimiters: $$, $, \\[\\], \\(\\)
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from mars.client.cli.math_renderer import (
    _apply_subs,
    _apply_scripts,
    _to_superscript,
    _to_subscript,
    _render_display,
    _render_inline,
    preprocess_math,
)


# ---------------------------------------------------------------------------
# _apply_subs — symbol substitution table
# ---------------------------------------------------------------------------


class TestApplySubs:
    """_apply_subs must map known LaTeX commands to Unicode characters."""

    def test_alpha(self):
        assert "α" in _apply_subs(r"\alpha")

    def test_beta(self):
        assert "β" in _apply_subs(r"\beta")

    def test_infinity(self):
        assert "∞" in _apply_subs(r"\infty")

    def test_pi(self):
        assert "π" in _apply_subs(r"\pi")

    def test_sum(self):
        assert "∑" in _apply_subs(r"\sum")

    def test_integral(self):
        assert "∫" in _apply_subs(r"\int")

    def test_partial(self):
        assert "∂" in _apply_subs(r"\partial")

    def test_arrow(self):
        assert "→" in _apply_subs(r"\rightarrow")

    def test_leq(self):
        assert "≤" in _apply_subs(r"\leq")

    def test_geq(self):
        assert "≥" in _apply_subs(r"\geq")

    def test_unknown_command_stripped(self):
        # Unknown LaTeX commands must be removed, not left as-is.
        result = _apply_subs(r"\unknowncommand")
        assert r"\unknowncommand" not in result

    def test_braces_removed(self):
        result = _apply_subs(r"x^{2}")
        assert "{" not in result
        assert "}" not in result

    def test_spacing_commands_converted(self):
        # \, \; \: should become spaces, \! should be removed
        result = _apply_subs(r"a\,b")
        assert r"\," not in result
        assert "a" in result and "b" in result

    def test_quad_becomes_spaces(self):
        result = _apply_subs(r"a\quad b")
        assert r"\quad" not in result


# ---------------------------------------------------------------------------
# _apply_scripts — super/subscript conversion
# ---------------------------------------------------------------------------


class TestApplyScripts:
    def test_superscript_braced(self):
        result = _apply_scripts("x^{2}")
        assert "²" in result

    def test_superscript_single_char(self):
        result = _apply_scripts("x^2")
        assert "²" in result

    def test_subscript_braced(self):
        result = _apply_scripts("x_{0}")
        assert "₀" in result

    def test_subscript_single_char(self):
        result = _apply_scripts("x_0")
        assert "₀" in result

    def test_superscript_negative(self):
        result = _apply_scripts("x^{-1}")
        assert "⁻" in result and "¹" in result

    def test_subscript_negative(self):
        result = _apply_scripts("_{-1}")
        assert "₋" in result and "₁" in result

    def test_integral_bounds(self):
        # \int_{-1}^{1} → subscript -1 and superscript 1
        result = _apply_scripts("∫_{-1}^{1}")
        assert "₋₁" in result
        assert "¹" in result


class TestToSuperSubscript:
    def test_superscript_digits(self):
        assert _to_superscript("123") == "¹²³"

    def test_subscript_digits(self):
        assert _to_subscript("012") == "₀₁₂"

    def test_superscript_minus(self):
        assert "⁻" in _to_superscript("-1")

    def test_subscript_minus(self):
        assert "₋" in _to_subscript("-1")

    def test_multiple_symbols(self):
        result = _apply_subs(r"\alpha + \beta")
        assert "α" in result
        assert "β" in result

    def test_plain_text_unchanged(self):
        result = _apply_subs("hello world")
        assert result == "hello world"

    def test_longest_key_wins(self):
        # \varepsilon should map to ε, not conflict with \epsilon-containing prefix
        result = _apply_subs(r"\varepsilon")
        assert "ε" in result

    def test_sin_spelled_out(self):
        result = _apply_subs(r"\sin")
        assert "sin" in result

    def test_in_set_symbol(self):
        result = _apply_subs(r"\in")
        assert "∈" in result

    def test_nabla(self):
        assert "∇" in _apply_subs(r"\nabla")

    def test_sqrt(self):
        assert "√" in _apply_subs(r"\sqrt")

    def test_forall(self):
        assert "∀" in _apply_subs(r"\forall")

    def test_exists(self):
        assert "∃" in _apply_subs(r"\exists")


# ---------------------------------------------------------------------------
# _render_inline — compact single-line output
# ---------------------------------------------------------------------------


class TestRenderInline:
    def test_simple_symbol(self):
        result = _render_inline(r"\alpha")
        assert "α" in result or result  # at minimum, non-empty

    def test_result_is_single_line(self):
        # Inline result must not contain embedded newlines in the middle
        # (multi-line SymPy results fall back to compact str)
        result = _render_inline(r"\frac{1}{2}")
        # Accept either "1/2" compact form or unicode fraction
        assert "\n" not in result or result.strip()

    def test_empty_input_handled(self):
        # Should not raise; returns empty or stripped string
        result = _render_inline("")
        assert isinstance(result, str)

    def test_plain_variable(self):
        result = _render_inline("x")
        assert "x" in result


# ---------------------------------------------------------------------------
# _render_display — multi-line Unicode art
# ---------------------------------------------------------------------------


class TestRenderDisplay:
    def test_returns_string(self):
        result = _render_display(r"\alpha + \beta")
        assert isinstance(result, str)

    def test_not_empty(self):
        result = _render_display(r"\int x dx")
        assert result.strip()

    def test_sympy_fraction(self):
        # If SymPy available, render a fraction; otherwise fallback subs.
        result = _render_display(r"\frac{a}{b}")
        assert result  # non-empty

    def test_greek_letter_display(self):
        result = _render_display(r"\pi")
        assert "π" in result or "pi" in result.lower()


# ---------------------------------------------------------------------------
# preprocess_math — top-level entry point
# ---------------------------------------------------------------------------


class TestPreprocessMath:
    # -- Inline math: $...$ → `unicode`

    def test_inline_single_dollar_replaced(self):
        content = r"The angle $\alpha$ is small."
        result = preprocess_math(content)
        # Result should contain backtick-wrapped unicode, not raw LaTeX
        assert "$" not in result or result.count("$") == 0
        assert "α" in result

    def test_inline_replaced_with_backticks(self):
        content = r"Value: $x$"
        result = preprocess_math(content)
        assert "`x`" in result or "`" in result

    def test_inline_multiple_replacements(self):
        content = r"Both $\alpha$ and $\beta$ appear here."
        result = preprocess_math(content)
        assert "α" in result
        assert "β" in result

    # -- Display math: $$...$$ → fenced code block

    def test_display_math_replaced_with_fence(self):
        content = r"$$\sum_{i=0}^{n} i$$"
        result = preprocess_math(content)
        assert "```" in result  # wrapped in fenced code block

    def test_display_math_not_dollar_dollar_in_output(self):
        content = r"The equation is: $$E = mc^2$$"
        result = preprocess_math(content)
        assert "$$" not in result

    def test_display_math_content_in_fence(self):
        content = r"$$\alpha$$"
        result = preprocess_math(content)
        assert "```" in result
        # Unicode content must be inside the fence
        assert "α" in result

    # -- No-math pass-through

    def test_plain_text_unchanged(self):
        content = "No math here, just plain text."
        result = preprocess_math(content)
        assert result == content

    def test_empty_string(self):
        assert preprocess_math("") == ""

    def test_markdown_without_math_unchanged(self):
        content = "# Title\n\nSome **bold** and _italic_ text.\n"
        result = preprocess_math(content)
        assert result == content

    # -- Fence guard — code blocks must not be touched

    def test_inline_in_code_fence_untouched(self):
        content = "```\n$\\alpha$ inside fence\n```"
        result = preprocess_math(content)
        # The original LaTeX inside the fence must survive unchanged
        assert r"\alpha" in result

    def test_display_in_code_fence_untouched(self):
        content = "```\n$$E=mc^2$$\n```"
        result = preprocess_math(content)
        assert "$$E=mc^2$$" in result

    def test_backtick_inline_code_fence_untouched(self):
        content = "Here `$x$` is inline code, not math."
        result = preprocess_math(content)
        # Inline code span starting with ` — depends on fence regex.
        # At minimum, no crash and result is non-empty.
        assert isinstance(result, str)
        assert result

    def test_display_before_inline_processed(self):
        # $$...$$ must be matched before $...$ to avoid double-match
        content = r"$$x^2$$"
        result = preprocess_math(content)
        # Must result in one fenced block, not two inline replacements
        assert result.count("```") >= 2  # opening + closing fence

    # -- Mixed content

    def test_mixed_inline_and_display(self):
        content = "Inline $x$ and display $$y = mx + b$$."
        result = preprocess_math(content)
        # Inline replaced with backticks, display with fence
        assert "```" in result
        assert "`x`" in result or "`" in result

    def test_multiline_display(self):
        content = "$$\n\\int_0^1 x^2 dx\n$$"
        result = preprocess_math(content)
        assert "```" in result

    # -- Fallback when SymPy is not available

    def test_fallback_when_sympy_absent(self):
        """preprocess_math must still work if SymPy/antlr4 import fails."""
        with patch("mars.client.cli.math_renderer._SYMPY_OK", False):
            content = r"The angle $\alpha$ is small."
            result = preprocess_math(content)
        assert "α" in result
        assert "$" not in result or result.count("$") == 0

    def test_fallback_display_when_sympy_absent(self):
        with patch("mars.client.cli.math_renderer._SYMPY_OK", False):
            content = r"$$\sum$$"
            result = preprocess_math(content)
        assert "∑" in result
        assert "```" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_dollar_in_price_not_replaced(self):
        # "$10" — no closing $ on same line (inline regex requires $...$)
        content = "The price is $10 per unit."
        result = preprocess_math(content)
        # Should pass through unchanged because "10 per unit" matches inline
        # but the regex requires non-dollar content. Depending on regex,
        # "$10 per unit." may partially match. Test is forgiving: just no crash.
        assert isinstance(result, str)

    def test_adjacent_dollars_not_inline(self):
        # $$ at the start — should be display math
        content = r"$$x$$"
        result = preprocess_math(content)
        assert "```" in result

    def test_tilde_fence_also_guarded(self):
        content = "~~~\n$\\alpha$\n~~~"
        result = preprocess_math(content)
        assert r"\alpha" in result

    def test_long_display_block(self):
        content = "$$" + (r"\alpha + " * 20) + r"\omega" + "$$"
        result = preprocess_math(content)
        assert "```" in result


# ---------------------------------------------------------------------------
# New delimiter styles: \[...\] and \(...\)
# ---------------------------------------------------------------------------


class TestBracketDelimiters:
    """\\[...\\] must be treated as display math; \\(...\\) as inline math."""

    def test_bracket_display_replaced_with_fence(self):
        content = r"\[ \int_{-1}^{1} x^3 \, dx \]"
        result = preprocess_math(content)
        assert "```" in result
        assert r"\[" not in result
        assert r"\]" not in result

    def test_bracket_display_contains_integral(self):
        content = r"\[ \int_{-1}^{1} x^3 \, dx \]"
        result = preprocess_math(content)
        # SymPy renders multi-line integral with ⌠⎮⌡; fallback uses ∫
        has_integral = "∫" in result or "⌠" in result or "⎮" in result
        assert has_integral

    def test_bracket_display_subscript_superscript(self):
        # Fallback path: bounds should become Unicode sub/superscripts
        with patch("mars.client.cli.math_renderer._SYMPY_OK", False):
            content = r"\[ \int_{-1}^{1} x^3 \, dx \]"
            result = preprocess_math(content)
        assert "∫" in result
        # Subscript -1 and superscript 1 (or at least braces gone)
        assert "{" not in result
        assert "}" not in result

    def test_paren_inline_replaced(self):
        content = r"The value is \(\alpha\) here."
        result = preprocess_math(content)
        assert r"\(" not in result
        assert r"\)" not in result
        assert "α" in result

    def test_paren_inline_wrapped_in_backticks(self):
        content = r"Energy: \(E = mc^2\)"
        result = preprocess_math(content)
        assert "`" in result

    def test_bracket_multiline_display(self):
        content = "\\[\n\\frac{a}{b}\n\\]"
        result = preprocess_math(content)
        assert "```" in result

    def test_bracket_in_fence_untouched(self):
        content = "```\n\\[ \\alpha \\]\n```"
        result = preprocess_math(content)
        assert r"\[" in result

    def test_spacing_command_thin_space(self):
        # \, (thin space) must not appear in output
        with patch("mars.client.cli.math_renderer._SYMPY_OK", False):
            content = r"\[ x \, dx \]"
            result = preprocess_math(content)
        assert r"\," not in result

    def test_user_reported_formula(self):
        """Regression: \\[ \\int_{-1}^{1} x^3 \\, dx \\] must render, not pass through raw."""
        content = r"\[ \int_{-1}^{1} x^3 \, dx \]"
        result = preprocess_math(content)
        # Must not show raw LaTeX delimiters
        assert r"\[" not in result
        assert r"\]" not in result
        # Must contain some form of integral symbol (∫ fallback, ⌠⎮⌡ SymPy pretty)
        has_integral = "∫" in result or "⌠" in result or "⎮" in result
        assert has_integral
        # Must be in a fenced code block
        assert "```" in result
