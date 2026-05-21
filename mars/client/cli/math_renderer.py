"""Terminal math rendering — converts LaTeX math blocks to Unicode art.

Display math (``$$...$$`` or ``\\[...\\]``) is rendered as multi-line Unicode art
wrapped in a fenced code block so Rich Markdown preserves the spacing.  Inline math
(``$...$`` or ``\\(...\\)``) is rendered to a compact single-line Unicode string.

SymPy + antlr4-python3-runtime handle full LaTeX parsing.  When parsing
fails (unsupported notation or parse error) the renderer falls back to a
symbol-substitution table that covers the most common LaTeX commands.
"""
from __future__ import annotations

import re

# ── SymPy / antlr4 optional import ──────────────────────────────────────────
try:
    from sympy.parsing.latex import parse_latex as _parse_latex
    import sympy as _sympy
    _SYMPY_OK = True
except Exception:
    _SYMPY_OK = False

# ── Unicode fallback symbol table ────────────────────────────────────────────
_UNICODE_SUBS: dict[str, str] = {
    # Greek lowercase
    r"\alpha": "α",   r"\beta": "β",    r"\gamma": "γ",   r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ",   r"\vartheta": "θ", r"\iota": "ι",  r"\kappa": "κ",
    r"\lambda": "λ",  r"\mu": "μ",      r"\nu": "ν",      r"\xi": "ξ",
    r"\pi": "π",      r"\varpi": "π",   r"\rho": "ρ",     r"\varrho": "ρ",
    r"\sigma": "σ",   r"\varsigma": "ς", r"\tau": "τ",    r"\upsilon": "υ",
    r"\phi": "φ",     r"\varphi": "φ",  r"\chi": "χ",     r"\psi": "ψ",
    r"\omega": "ω",
    # Greek uppercase
    r"\Gamma": "Γ",   r"\Delta": "Δ",   r"\Theta": "Θ",   r"\Lambda": "Λ",
    r"\Xi": "Ξ",      r"\Pi": "Π",      r"\Sigma": "Σ",   r"\Phi": "Φ",
    r"\Psi": "Ψ",     r"\Omega": "Ω",
    # Operators and constants
    r"\infty": "∞",   r"\partial": "∂", r"\nabla": "∇",   r"\hbar": "ℏ",
    r"\ell": "ℓ",     r"\Re": "ℜ",      r"\Im": "ℑ",
    r"\pm": "±",      r"\mp": "∓",      r"\times": "×",   r"\div": "÷",
    r"\cdot": "·",    r"\circ": "∘",    r"\bullet": "•",
    r"\leq": "≤",     r"\geq": "≥",     r"\neq": "≠",     r"\approx": "≈",
    r"\equiv": "≡",   r"\sim": "∼",     r"\simeq": "≃",   r"\cong": "≅",
    r"\propto": "∝",  r"\ll": "≪",      r"\gg": "≫",
    # Sets and logic
    r"\in": "∈",      r"\notin": "∉",   r"\subset": "⊂",  r"\supset": "⊃",
    r"\subseteq": "⊆", r"\supseteq": "⊇",
    r"\cup": "∪",     r"\cap": "∩",     r"\emptyset": "∅", r"\varnothing": "∅",
    r"\forall": "∀",  r"\exists": "∃",  r"\nexists": "∄", r"\neg": "¬",
    r"\wedge": "∧",   r"\vee": "∨",     r"\oplus": "⊕",
    # Arrows
    r"\to": "→",          r"\rightarrow": "→",  r"\leftarrow": "←",
    r"\leftrightarrow": "↔", r"\Rightarrow": "⇒", r"\Leftarrow": "⇐",
    r"\Leftrightarrow": "⇔", r"\uparrow": "↑",   r"\downarrow": "↓",
    r"\mapsto": "↦",
    # Calculus and analysis
    r"\int": "∫",     r"\iint": "∬",    r"\iiint": "∭",   r"\oint": "∮",
    r"\sum": "∑",     r"\prod": "∏",    r"\sqrt": "√",
    # Functions (keep spelled out but strip backslash)
    r"\log": "log",   r"\ln": "ln",     r"\exp": "exp",   r"\lim": "lim",
    r"\sin": "sin",   r"\cos": "cos",   r"\tan": "tan",
    r"\arcsin": "arcsin", r"\arccos": "arccos", r"\arctan": "arctan",
    r"\sinh": "sinh", r"\cosh": "cosh", r"\tanh": "tanh",
    r"\max": "max",   r"\min": "min",   r"\sup": "sup",   r"\inf": "inf",
    r"\det": "det",   r"\dim": "dim",   r"\ker": "ker",
    # Spacing commands → single space
    r"\,": " ",   r"\;": " ",   r"\:": " ",   r"\!": "",
    r"\ ": " ",   r"\quad": "  ",  r"\qquad": "    ",
    # Misc
    r"\ldots": "…",   r"\cdots": "⋯",   r"\vdots": "⋮",   r"\ddots": "⋱",
    r"\|": "‖",       r"\%": "%",
}

# Unicode super/subscript maps for single characters
_SUPERSCRIPT_MAP: dict[str, str] = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "n": "ⁿ", "i": "ⁱ", "a": "ᵃ",
    "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "k": "ᵏ",
    "m": "ᵐ", "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ",
    "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ",
    "z": "ᶻ",
}
_SUBSCRIPT_MAP: dict[str, str] = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "n": "ₙ", "i": "ᵢ", "a": "ₐ",
    "e": "ₑ", "o": "ₒ", "j": "ⱼ",
}


def _to_superscript(s: str) -> str:
    return "".join(_SUPERSCRIPT_MAP.get(c, c) for c in s)


def _to_subscript(s: str) -> str:
    return "".join(_SUBSCRIPT_MAP.get(c, c) for c in s)


def _apply_scripts(latex: str) -> str:
    """Convert ^{...} / _{...} and ^x / _x to Unicode super/subscripts."""
    # Braced forms first: ^{...} and _{...}
    latex = re.sub(r"\^\{([^}]*)\}", lambda m: _to_superscript(m.group(1)), latex)
    latex = re.sub(r"_\{([^}]*)\}",  lambda m: _to_subscript(m.group(1)),   latex)
    # Single-char shorthand: ^x and _x (not followed by { )
    latex = re.sub(r"\^([^\{])",  lambda m: _to_superscript(m.group(1)), latex)
    latex = re.sub(r"_([^\{])",   lambda m: _to_subscript(m.group(1)),   latex)
    return latex


def _apply_subs(latex: str) -> str:
    """Replace known LaTeX commands with Unicode characters (longest key first)."""
    result = latex
    for cmd, uni in sorted(_UNICODE_SUBS.items(), key=lambda kv: -len(kv[0])):
        result = result.replace(cmd, uni)
    result = _apply_scripts(result)
    result = re.sub(r"\\[a-zA-Z]+\*?", "", result)   # drop unknown commands
    result = re.sub(r"[{}]", "", result).strip()       # strip remaining braces
    return result


# ── Delimiter regexes ─────────────────────────────────────────────────────────
# Display math: $$...$$ or \[...\]  (matched before inline)
_RE_DISPLAY        = re.compile(r"\$\$(.*?)\$\$",      re.DOTALL)
_RE_DISPLAY_BRACKET = re.compile(r"\\\[(.*?)\\\]",     re.DOTALL)
# Inline math: $...$ or \(...\)
_RE_INLINE         = re.compile(r"(?<!\$)\$([^\$\n]+?)\$(?!\$)")
_RE_INLINE_PAREN   = re.compile(r"\\\((.+?)\\\)")
# Fenced code blocks (backtick or tilde) — math inside code is left untouched.
_RE_FENCE          = re.compile(r"(`{3,}|~{3,}).*?\1", re.DOTALL)


def _render_display(latex: str) -> str:
    """Render display-mode LaTeX to multi-line Unicode art."""
    latex = latex.strip()
    if _SYMPY_OK:
        try:
            expr = _parse_latex(latex)
            return _sympy.pretty(expr, use_unicode=True)
        except Exception:
            pass
    return _apply_subs(latex)


def _render_inline(latex: str) -> str:
    """Render inline LaTeX to a compact single-line Unicode string."""
    latex = latex.strip()
    if _SYMPY_OK:
        try:
            expr = _parse_latex(latex)
            pretty = _sympy.pretty(expr, use_unicode=True)
            lines = [ln for ln in pretty.splitlines() if ln.strip()]
            if len(lines) == 1:
                return lines[0]
            # Multi-line result (e.g. fraction) — use compact str representation
            return str(expr)
        except Exception:
            pass
    return _apply_subs(latex)


def preprocess_math(content: str) -> str:
    """Replace LaTeX math delimiters in *content* with Unicode terminal art.

    Recognized delimiters:
    - ``$$...$$`` and ``\\[...\\]``  →  fenced code block (display math)
    - ``$...$``   and ``\\(...\\)``  →  inline backtick-wrapped Unicode

    Code fences in the original content are left untouched.
    """
    # Collect the positions of fenced code blocks so we don't touch them.
    fenced_spans: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in _RE_FENCE.finditer(content)
    ]

    def _in_fence(start: int) -> bool:
        return any(fs <= start < fe for fs, fe in fenced_spans)

    def _repl_display(m: "re.Match[str]") -> str:
        if _in_fence(m.start()):
            return m.group(0)
        rendered = _render_display(m.group(1))
        indented = "\n".join("  " + line for line in rendered.splitlines())
        return f"\n```\n{indented}\n```\n"

    def _repl_inline(m: "re.Match[str]") -> str:
        if _in_fence(m.start()):
            return m.group(0)
        rendered = _render_inline(m.group(1))
        return f"`{rendered}`"

    # ── Display math (both delimiter styles) ─────────────────────────────────
    content = _RE_DISPLAY.sub(_repl_display, content)
    content = _RE_DISPLAY_BRACKET.sub(_repl_display, content)

    # Recompute fence spans after display substitution (offsets changed).
    fenced_spans = [(m.start(), m.end()) for m in _RE_FENCE.finditer(content)]

    # ── Inline math (both delimiter styles) ──────────────────────────────────
    content = _RE_INLINE.sub(_repl_inline, content)
    content = _RE_INLINE_PAREN.sub(_repl_inline, content)

    return content
