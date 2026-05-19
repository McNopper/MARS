"""MARS SciPy Math Service Agent — numerical mathematics via SciPy.

Complements the SymPy agent (symbolic) with fast numerical computation.
The caller (an LLM agent) must send a structured expression — not free-form
natural language.  Supported request formats:

Numerical integration
---------------------
  quad(x**2, 0, 1)                         → ∫₀¹ x² dx
  dblquad(x*y, 0, 1, 0, 1)                 → ∫∫ x·y dx dy

Root finding
------------
  fsolve(x**2 - 4, 2.0)                    → numerical root near x=2
  brentq(x**2 - 4, 0, 3)                   → root in bracket [0,3]
  newton(x**2 - 4, 1.5)                    → Newton / secant method

Optimization
------------
  minimize(x**2 + 2*x + 1, 0)              → scalar minimisation
  minimize((x-2)**2 + (y-3)**2, [0, 0])    → 2-D minimisation (vars x,y)

Linear algebra
--------------
  solve([[1,2],[3,4]], [5,6])               → Ax=b
  det([[1,2],[3,4]])                        → determinant
  inv([[1,2],[3,4]])                        → matrix inverse
  eig([[1,2],[3,4]])                        → eigenvalues + eigenvectors
  lstsq([[1,1],[1,2],[1,3]], [1,2,3])       → least squares

Statistics (scipy.stats)
------------------------
  norm.cdf(1.96)                            → CDF of standard normal
  norm.pdf(0, 0, 1)                         → PDF(x=0, μ=0, σ=1)
  norm.ppf(0.975)                           → inverse CDF
  t.cdf(2.0, df=10)                         → Student-t CDF
  chi2.pdf(3.0, df=5)                       → chi-squared PDF
  binom.pmf(3, n=10, p=0.5)                 → binomial PMF

ODE solving
-----------
  solve_ivp(dy=-y, t=[0,5], y0=[1.0])       → dy/dt = -y, IVP solution
  solve_ivp(dy=sin(t), t=[0,6.28], y0=[0])  → dy/dt = sin(t)

Response fields
---------------
  operation   detected operation name
  result      primary numerical result (float / list / dict)
  error       error message (only present on failure)
  extra       ancillary data (e.g. infodict from quad, message from minimize)
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import re
from typing import Any

from mars.services.mcp_server import MCPServer


# ---------------------------------------------------------------------------
# Safe numerical namespace for eval
# ---------------------------------------------------------------------------

def _safe_ns() -> dict[str, Any]:
    """Return a minimal safe namespace for evaluating numerical expressions."""
    import numpy as np
    return {
        "__builtins__": {},
        # trig
        "sin": np.sin, "cos": np.cos, "tan": np.tan,
        "arcsin": np.arcsin, "arccos": np.arccos, "arctan": np.arctan, "arctan2": np.arctan2,
        "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
        # exponential / log
        "exp": np.exp, "log": np.log, "log2": np.log2, "log10": np.log10,
        "sqrt": np.sqrt, "cbrt": np.cbrt,
        # rounding / misc
        "abs": np.abs, "sign": np.sign, "ceil": np.ceil, "floor": np.floor,
        "round": round, "max": np.maximum, "min": np.minimum,
        # constants
        "pi": np.pi, "e": np.e, "inf": np.inf, "nan": np.nan,
        # numpy
        "np": np, "array": np.array,
    }


def _make_func(expr_str: str, vars_: list[str] | None = None) -> Any:
    """Compile *expr_str* into a callable ``lambda vars...: expr``."""
    if vars_ is None:
        vars_ = _detect_vars(expr_str)
    ns = _safe_ns()
    args = ", ".join(vars_) if vars_ else "x"
    return eval(f"lambda {args}: {expr_str}", ns)  # noqa: S307


def _detect_vars(expr: str) -> list[str]:
    """Heuristically detect free variable names in a math expression."""
    tokens = set(re.findall(r"\b([a-z][a-z0-9_]*)\b", expr))
    known = set(_safe_ns())
    free = sorted(t for t in tokens if t not in known and len(t) <= 3)
    return free if free else ["x"]


def _parse_literal(text: str) -> Any:
    """Parse a Python literal (list / tuple / number) from text."""
    try:
        return ast.literal_eval(text.strip())
    except Exception:
        return float(text.strip())


def _parse_args(inner: str) -> list[str]:
    """Split a comma-separated argument list, respecting brackets/parens."""
    depth = 0
    parts: list[str] = []
    current: list[str] = []
    for ch in inner:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


# ---------------------------------------------------------------------------
# SciPy operation handlers
# ---------------------------------------------------------------------------

def _op_quad(args: list[str]) -> dict[str, Any]:
    from scipy import integrate  # type: ignore[import]
    if len(args) < 3:
        return {"error": "quad requires: quad(expr, a, b)"}
    func = _make_func(args[0], ["x"])
    a, b = _parse_literal(args[1]), _parse_literal(args[2])
    val, err = integrate.quad(func, a, b)
    return {"operation": "quad", "result": val, "extra": {"absolute_error": err}}


def _op_dblquad(args: list[str]) -> dict[str, Any]:
    from scipy import integrate  # type: ignore[import]
    if len(args) < 5:
        return {"error": "dblquad requires: dblquad(expr, ax, bx, ay, by)"}
    func = _make_func(args[0], ["y", "x"])
    ax, bx = _parse_literal(args[1]), _parse_literal(args[2])
    ay, by = _parse_literal(args[3]), _parse_literal(args[4])
    val, err = integrate.dblquad(func, ax, bx, ay, by)
    return {"operation": "dblquad", "result": val, "extra": {"absolute_error": err}}


def _op_fsolve(args: list[str]) -> dict[str, Any]:
    from scipy import optimize  # type: ignore[import]
    import numpy as np
    if len(args) < 2:
        return {"error": "fsolve requires: fsolve(expr, x0)"}
    func = _make_func(args[0])
    x0 = _parse_literal(args[1])
    sol = optimize.fsolve(func, x0, full_output=True)
    roots = sol[0].tolist() if hasattr(sol[0], "tolist") else list(sol[0])
    return {"operation": "fsolve", "result": roots[0] if len(roots) == 1 else roots}


def _op_brentq(args: list[str]) -> dict[str, Any]:
    from scipy import optimize  # type: ignore[import]
    if len(args) < 3:
        return {"error": "brentq requires: brentq(expr, a, b)"}
    func = _make_func(args[0], ["x"])
    a, b = _parse_literal(args[1]), _parse_literal(args[2])
    root = optimize.brentq(func, a, b)
    return {"operation": "brentq", "result": root}


def _op_newton(args: list[str]) -> dict[str, Any]:
    from scipy import optimize  # type: ignore[import]
    if len(args) < 2:
        return {"error": "newton requires: newton(expr, x0)"}
    func = _make_func(args[0], ["x"])
    x0 = _parse_literal(args[1])
    root = optimize.newton(func, x0)
    return {"operation": "newton", "result": float(root)}


def _op_minimize(args: list[str]) -> dict[str, Any]:
    from scipy import optimize  # type: ignore[import]
    import numpy as np
    if len(args) < 2:
        return {"error": "minimize requires: minimize(expr, x0)"}
    free = _detect_vars(args[0])
    func_vec = _make_func(args[0], free) if len(free) > 1 else _make_func(args[0], ["x"])
    # wrap multi-var lambda: receives array, maps to named args
    if len(free) > 1:
        def _wrap(v: Any) -> Any:
            return func_vec(*v)
        func = _wrap
    else:
        func = func_vec
    x0 = _parse_literal(args[1])
    method = args[2].strip().strip("'\"") if len(args) > 2 else None
    res = optimize.minimize(func, x0, method=method)
    xval = res.x.tolist() if hasattr(res.x, "tolist") else res.x
    return {
        "operation": "minimize",
        "result": xval[0] if len(xval) == 1 else xval,
        "extra": {"fun": float(res.fun), "success": res.success, "message": res.message},
    }


def _op_linalg_solve(args: list[str]) -> dict[str, Any]:
    from scipy import linalg  # type: ignore[import]
    import numpy as np
    if len(args) < 2:
        return {"error": "solve requires: solve(A, b)"}
    A = np.array(_parse_literal(args[0]), dtype=float)
    b = np.array(_parse_literal(args[1]), dtype=float)
    x = linalg.solve(A, b)
    return {"operation": "solve", "result": x.tolist()}


def _op_det(args: list[str]) -> dict[str, Any]:
    from scipy import linalg  # type: ignore[import]
    import numpy as np
    A = np.array(_parse_literal(args[0]), dtype=float)
    return {"operation": "det", "result": float(linalg.det(A))}


def _op_inv(args: list[str]) -> dict[str, Any]:
    from scipy import linalg  # type: ignore[import]
    import numpy as np
    A = np.array(_parse_literal(args[0]), dtype=float)
    return {"operation": "inv", "result": linalg.inv(A).tolist()}


def _op_eig(args: list[str]) -> dict[str, Any]:
    from scipy import linalg  # type: ignore[import]
    import numpy as np
    A = np.array(_parse_literal(args[0]), dtype=float)
    vals, vecs = linalg.eig(A)
    # Convert complex → real when imaginary part is negligible
    def _clean(v: Any) -> Any:
        if hasattr(v, "imag") and abs(v.imag) < 1e-10:
            return float(v.real)
        return complex(v)
    eigenvalues = [_clean(v) for v in vals]
    eigenvectors = [[_clean(vecs[r, c]) for r in range(vecs.shape[0])]
                    for c in range(vecs.shape[1])]
    return {"operation": "eig", "result": {"eigenvalues": eigenvalues, "eigenvectors": eigenvectors}}


def _op_lstsq(args: list[str]) -> dict[str, Any]:
    from scipy import linalg  # type: ignore[import]
    import numpy as np
    if len(args) < 2:
        return {"error": "lstsq requires: lstsq(A, b)"}
    A = np.array(_parse_literal(args[0]), dtype=float)
    b = np.array(_parse_literal(args[1]), dtype=float)
    x, res, rank, sv = linalg.lstsq(A, b)
    return {
        "operation": "lstsq",
        "result": x.tolist(),
        "extra": {"rank": int(rank), "singular_values": sv.tolist()},
    }


def _op_stats(func_name: str, args: list[str]) -> dict[str, Any]:
    """Handle scipy.stats calls: norm.cdf(x), t.pdf(x, df=n), etc."""
    from scipy import stats  # type: ignore[import]
    # Map plain names to scipy.stats distributions
    dist_map = {
        "norm": stats.norm, "t": stats.t, "chi2": stats.chi2,
        "f": stats.f, "expon": stats.expon, "uniform": stats.uniform,
        "poisson": stats.poisson, "binom": stats.binom, "beta": stats.beta,
        "gamma": stats.gamma, "lognorm": stats.lognorm,
    }
    # func_name is e.g. "norm.cdf", "t.ppf"
    parts = func_name.split(".")
    dist_name, method = parts[0], parts[1] if len(parts) > 1 else "cdf"
    dist = dist_map.get(dist_name)
    if dist is None:
        return {"error": f"Unknown distribution: {dist_name!r}"}
    fn = getattr(dist, method, None)
    if fn is None:
        return {"error": f"Unknown method {method!r} on {dist_name}"}

    # Parse positional args and keyword args (e.g. "df=5", "p=0.5")
    positional: list[Any] = []
    kwargs: dict[str, Any] = {}
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            kwargs[k.strip()] = _parse_literal(v.strip())
        else:
            positional.append(_parse_literal(a))

    result = fn(*positional, **kwargs)
    return {"operation": f"{dist_name}.{method}", "result": float(result)}


def _op_solve_ivp(args: list[str]) -> dict[str, Any]:
    """solve_ivp(dy=expr, t=[t0,t1], y0=[v0,...])"""
    from scipy import integrate  # type: ignore[import]
    import numpy as np
    # Parse keyword-style arguments
    kw: dict[str, str] = {}
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            kw[k.strip()] = v.strip()
        else:
            kw.setdefault("_expr", a)
    dy_expr = kw.get("dy") or kw.get("_expr")
    if dy_expr is None:
        return {"error": "solve_ivp requires: solve_ivp(dy=expr, t=[t0,t1], y0=[v0])"}
    t_span_raw = kw.get("t")
    y0_raw = kw.get("y0")
    if t_span_raw is None or y0_raw is None:
        return {"error": "solve_ivp requires t=[t0,t1] and y0=[v0] arguments"}
    t_span = _parse_literal(t_span_raw)
    y0 = _parse_literal(y0_raw)
    if not isinstance(y0, list):
        y0 = [y0]
    # Build the RHS: f(t, y) — dy_expr uses 't' as time, 'y' as state vector y[0]
    ns = _safe_ns()
    rhs_fn = eval(f"lambda t, y: [{dy_expr.replace('y', 'y[0]')}]", ns)  # noqa: S307
    sol = integrate.solve_ivp(rhs_fn, t_span, y0, dense_output=False)
    t_pts = sol.t.tolist()
    y_pts = sol.y.tolist()
    return {
        "operation": "solve_ivp",
        "result": {
            "t": t_pts,
            "y": y_pts,
            "success": sol.success,
            "message": sol.message,
        },
    }


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_STATS_RE = re.compile(
    r"^(norm|t|chi2|f|expon|uniform|poisson|binom|beta|gamma|lognorm)"
    r"\.(cdf|pdf|pmf|ppf|sf|isf|logcdf|logpdf|logpmf)\s*\(",
    re.I,
)
_SOLVE_IVP_RE = re.compile(r"^solve_ivp\s*\(", re.I)


def _dispatch_request(text: str) -> dict[str, Any]:
    """Route *text* to the appropriate SciPy handler and return a result dict.

    The caller is responsible for sending a clean structured expression — not
    free-form natural language.
    """
    t = text.strip()

    try:
        # --- stats: norm.cdf(x), t.ppf(p, df=n), ... -------------------------
        m_stats = _STATS_RE.match(t)
        if m_stats:
            func_name = f"{m_stats.group(1)}.{m_stats.group(2)}"
            inner = re.match(r"^[a-z2]+\.[a-z]+\s*\((.+)\)$", t, re.I)
            args = _parse_args(inner.group(1)) if inner else []
            return _op_stats(func_name, args)

        # --- solve_ivp --------------------------------------------------------
        if _SOLVE_IVP_RE.match(t):
            inner = re.match(r"^solve_ivp\s*\((.+)\)$", t, re.I | re.S)
            args = _parse_args(inner.group(1)) if inner else []
            return _op_solve_ivp(args)

        # --- other function calls ---------------------------------------------
        m_call = re.match(r"^([a-z_][a-z0-9_]*)\s*\((.+)\)$", t, re.I | re.S)
        if not m_call:
            return {"error": f"Unrecognised request format: {t!r}"}

        fname = m_call.group(1).lower()
        args = _parse_args(m_call.group(2))

        dispatch = {
            "quad":     _op_quad,
            "dblquad":  _op_dblquad,
            "fsolve":   _op_fsolve,
            "brentq":   _op_brentq,
            "newton":   _op_newton,
            "minimize": _op_minimize,
            "solve":    _op_linalg_solve,
            "det":      _op_det,
            "inv":      _op_inv,
            "eig":      _op_eig,
            "lstsq":    _op_lstsq,
        }

        handler = dispatch.get(fname)
        if handler is None:
            return {"error": f"Unknown operation {fname!r}. "
                             f"Supported: {', '.join(sorted(dispatch))}"}
        return handler(args)

    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Agent wire loop
# ---------------------------------------------------------------------------

def _format_scipy_result(d: dict) -> str:
    if "error" in d:
        return f"❌ SciPy error: {d['error']}"
    op = d.get("operation", "result")
    result = d.get("result")
    extra = d.get("extra", {})
    lines = [f"📐 SciPy {op}:  {result}"]
    for k, v in (extra or {}).items():
        lines.append(f"   {k}: {v}")
    return "\n".join(lines)


async def run_agent(server: str) -> None:
    from mars.services.service_utils import build_hello, run_wire_agent
    await run_wire_agent(
        server,
        build_hello("svc.scipy@1", [
            "scipy", "numerical", "quadrature", "rootfind",
            "optimize", "linalg", "ode", "statistics", "stats",
        ]),
        _dispatch_request,
        "scipy_result.json",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="mars-agent-scipy",
        description="MARS SciPy numerical math MCP service agent",
    )
    parser.parse_args(argv)

    server = MCPServer("svc.scipy", "1.0.0")

    @server.tool(
        "solve_scipy",
        "Numerical mathematics via SciPy: integration, root-finding, optimization, "
        "linear algebra, statistics, and ODE solving.",
    )
    def solve_scipy(request: str) -> str:
        return _format_scipy_result(_dispatch_request(request))

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
