"""MARS Math Service Agent — solves equations and evaluates expressions with SymPy.

Accepts a plain-text math request and returns a JSON artifact with the result.

Supported operations (auto-detected from the input text)
---------------------------------------------------------
  solve       ``x**2 - 4 = 0``, ``solve(x**2 - 4, x)``
  simplify    ``simplify(sin(x)**2 + cos(x)**2)``
  expand      ``expand((x+1)**3)``
  factor      ``factor(x**2 - 1)``
  diff        ``diff(x**3, x)``, ``derivative of x^3``
  integrate   ``integrate(x**2, x)``, ``integral of x^2``
  limit       ``limit(sin(x)/x, x, 0)``
  evaluate    any other expression → numerical / symbolic evaluation

Response fields
---------------
  expression  Normalised input expression
  operation   Detected operation name
  result      SymPy result as a string
  latex       LaTeX representation (when available)
  numeric     Float approximation (when the result is a number)
  error       Error message (only present on failure)
"""
from __future__ import annotations

import argparse
import asyncio
import re
from typing import Any

from mars.runtime.services.mcp_server import MCPServer

# Regex to strip common natural-language question prefixes so the agent
# accepts inputs like "what is sin(5) * cos(8)" or "calculate x^2 - 4 = 0".
_NL_PREFIX_RE = re.compile(
    r"^(?:"
    r"what(?:'?s|\s+is|\s+are|\s+would\s+be)?|"
    r"please(?:\s+(?:calculate|compute|evaluate|find|solve|simplify|expand|factor|differentiate|integrate))?|"
    r"can\s+you(?:\s+(?:calculate|compute|evaluate|find|solve|simplify))?|"
    r"could\s+you(?:\s+(?:calculate|compute|evaluate|find|solve|simplify))?|"
    r"calculate|compute|evaluate|find|"
    r"help\s+(?:me\s+)?(?:with\s+)?(?:calculating|computing|evaluating|solving|finding)?|"
    r"(?:the\s+)?(?:value|result|answer)\s+(?:of|to|for)"
    r")\s*[,:?]?\s*",
    re.IGNORECASE,
)


def _strip_nl_prefix(text: str) -> str:
    """Strip natural-language question prefixes, returning the math part.

    Applies the regex repeatedly so stacked prefixes like
    "please calculate what is …" are fully removed.
    """
    result = text.strip(" \t\n?,.")
    while True:
        stripped = _NL_PREFIX_RE.sub("", result, count=1).strip(" \t\n?,.")
        if stripped == result:
            break
        result = stripped
    return result


def _solve_request(text: str) -> dict[str, Any]:
    """Evaluate *text* as a SymPy expression or equation.

    Accepts both clean math expressions and natural-language questions such as
    "what is sin(5) * cos(8)" or "calculate x^2 - 4 = 0".  Natural-language
    prefixes are stripped automatically before parsing.

    Supported formats:

    * ``x**2 - 4 = 0``             → solve for x
    * ``solve(x**2 - 4, x)``       → explicit solve call
    * ``diff(x**3, x)``            → differentiate
    * ``integrate(x**2, x)``       → indefinite integral
    * ``integrate(x**2, (x,0,1))`` → definite integral
    * ``integral of x**2``         → indefinite integral (convenience)
    * ``limit(sin(x)/x, x, 0)``    → limit
    * ``simplify(…)`` / ``expand(…)`` / ``factor(…)``
    * Any plain expression          → numeric / symbolic evaluation
    """
    try:
        import sympy as sp
        from sympy.parsing.sympy_parser import (
            parse_expr,
            standard_transformations,
            implicit_multiplication_application,
            convert_xor,
        )
    except ImportError:
        return {"error": "SymPy is not installed. Run: pip install sympy"}

    transformations = (
        standard_transformations
        + (implicit_multiplication_application, convert_xor)
    )

    def _parse(expr_str: str) -> sp.Expr:
        return parse_expr(expr_str.strip(), transformations=transformations)

    text_clean = _strip_nl_prefix(text.strip())
    if not text_clean:
        return {"error": "Empty expression after stripping prefixes."}
    operation = "evaluate"
    result_expr: Any = None

    try:
        # --- solve(expr, var) or expr = rhs -----------------------------------
        m_solve = re.match(
            r"^solve\s*\(\s*(.+?)\s*(?:,\s*([a-zA-Z_]\w*))?\s*\)$",
            text_clean, re.IGNORECASE,
        )
        m_eq = re.search(r"=", text_clean)

        if m_solve or (m_eq and not re.match(r"^(diff|integrate|limit|simplify|expand|factor)", text_clean, re.I)):
            operation = "solve"
            if m_solve:
                lhs_str = m_solve.group(1)
                var_name = m_solve.group(2) or "x"
            else:
                parts = text_clean.split("=", 1)
                lhs_str = f"({parts[0].strip()}) - ({parts[1].strip()})"
                var_name = "x"
            var = sp.Symbol(var_name)
            expr = _parse(lhs_str)
            result_expr = sp.solve(expr, var)

        # --- diff / derivative ------------------------------------------------
        elif re.match(r"^(diff\s*\(|derivative\s+of\s+)", text_clean, re.I):
            operation = "differentiate"
            m_d = re.match(r"^diff\s*\(\s*(.+?)\s*(?:,\s*([a-zA-Z_]\w*))?\s*\)$", text_clean, re.I)
            if m_d:
                expr = _parse(m_d.group(1))
                var = sp.Symbol(m_d.group(2) or "x")
            else:
                body = re.sub(r"^derivative\s+of\s+", "", text_clean, flags=re.I)
                expr = _parse(body)
                var = sp.Symbol("x")
            result_expr = sp.diff(expr, var)

        # --- integrate --------------------------------------------------------
        elif re.match(r"^(integrate\s*\(|integral\s+of\s+)", text_clean, re.I):
            operation = "integrate"
            m_i_def = re.match(
                r"^integrate\s*\(\s*(.+?)\s*,\s*\(?\s*([a-zA-Z_]\w*)\s*,\s*(.+?)\s*,\s*(.+?)\s*\)?\s*\)$",
                text_clean,
                re.I,
            )
            m_i_var = re.match(
                r"^integrate\s*\(\s*(.+?)\s*,\s*([a-zA-Z_]\w*)\s*\)$",
                text_clean,
                re.I,
            )
            m_i_expr = re.match(r"^integrate\s*\(\s*(.+)\s*\)$", text_clean, re.I)
            if m_i_def:
                expr = _parse(m_i_def.group(1))
                var = sp.Symbol(m_i_def.group(2))
                lo = _parse(m_i_def.group(3))
                hi = _parse(m_i_def.group(4))
                result_expr = sp.integrate(expr, (var, lo, hi))
            elif m_i_var:
                expr = _parse(m_i_var.group(1))
                result_expr = sp.integrate(expr, sp.Symbol(m_i_var.group(2)))
            elif m_i_expr:
                result_expr = sp.integrate(_parse(m_i_expr.group(1)), sp.Symbol("x"))
            else:
                body = re.sub(r"^integral\s+of\s+", "", text_clean, flags=re.I)
                result_expr = sp.integrate(_parse(body), sp.Symbol("x"))

        # --- limit ------------------------------------------------------------
        elif re.match(r"^limit\s*\(", text_clean, re.I):
            operation = "limit"
            m_l = re.match(
                r"^limit\s*\(\s*(.+?)\s*,\s*([a-zA-Z_]\w*)\s*,\s*(.+?)\s*\)$",
                text_clean, re.I,
            )
            if m_l:
                expr = _parse(m_l.group(1))
                var = sp.Symbol(m_l.group(2))
                pt = _parse(m_l.group(3))
                result_expr = sp.limit(expr, var, pt)
            else:
                return {"error": f"Cannot parse limit expression: {text_clean}"}

        # --- simplify ---------------------------------------------------------
        elif re.match(r"^simplify\s*\(", text_clean, re.I):
            operation = "simplify"
            inner = re.match(r"^simplify\s*\(\s*(.+)\s*\)$", text_clean, re.I)
            result_expr = sp.simplify(_parse(inner.group(1) if inner else text_clean))

        # --- expand -----------------------------------------------------------
        elif re.match(r"^expand\s*\(", text_clean, re.I):
            operation = "expand"
            inner = re.match(r"^expand\s*\(\s*(.+)\s*\)$", text_clean, re.I)
            result_expr = sp.expand(_parse(inner.group(1) if inner else text_clean))

        # --- factor -----------------------------------------------------------
        elif re.match(r"^factor\s*\(", text_clean, re.I):
            operation = "factor"
            inner = re.match(r"^factor\s*\(\s*(.+)\s*\)$", text_clean, re.I)
            result_expr = sp.factor(_parse(inner.group(1) if inner else text_clean))

        # --- fallback: just evaluate / simplify the expression ----------------
        else:
            operation = "evaluate"
            result_expr = sp.simplify(_parse(text_clean))

        result_str = str(result_expr)
        payload: dict[str, Any] = {
            "expression": text_clean,
            "operation":  operation,
            "result":     result_str,
        }
        try:
            payload["latex"] = sp.latex(result_expr)
        except Exception:
            pass
        try:
            numeric = float(sp.N(result_expr))
            payload["numeric"] = numeric
        except Exception:
            pass
        return payload

    except Exception as exc:  # noqa: BLE001
        return {"expression": text_clean, "operation": operation, "error": str(exc)}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Agent wire loop
# ---------------------------------------------------------------------------

def _format_math_result(result: dict) -> str:
    """Return a human-readable summary of a SymPy computation result."""
    if "error" in result:
        return f"⚠️  Error: {result['error']}"

    op      = result.get("operation", "evaluate").capitalize()
    expr    = result.get("expression", "")
    res     = result.get("result", "")
    numeric = result.get("numeric")

    lines = [f"🧮 {op}:  {expr}", f"→  {res}"]
    if numeric is not None:
        lines.append(f"≈  {numeric:g}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-sympy",
        description="MARS SymPy math MCP service agent",
    )
    parser.parse_args(argv)

    server = MCPServer("svc.sympy", "1.0.0")

    @server.tool(
        "solve_math",
        "Solve equations and evaluate symbolic/numeric expressions using SymPy. "
        "Accepts plain math expressions or natural-language questions.",
    )
    def solve_math(request: str) -> str:
        return _format_math_result(_solve_request(request))

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
