"""Tiny, safe formula engine for ``formula`` columns.

Expressions reference other numeric columns by key: ``salary + side``
or ``{salary} / 1000``. Parsed with :mod:`ast`, only a strict whitelist
of nodes is allowed; anything else raises ``ValueError``.
"""

from __future__ import annotations

import ast
import builtins
import re
from typing import Any

_NAME_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Call,
)
_ALLOWED_CALLS = {"round", "abs", "min", "max"}


def referenced_columns(expression: str) -> list[str]:
    """Column keys used by the expression (``{col}`` or bare ``col`` names).

    Whitelisted callables (round/abs/min/max) are excluded — they're
    functions, not column references.
    """
    expr = _normalize(expression)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    return sorted(
        {
            n.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id not in _ALLOWED_CALLS
        }
    )


def evaluate(expression: str, row: dict[str, Any]) -> float:
    """Evaluate ``expression`` against ``row`` values; raises ValueError."""
    expr = _normalize(expression)
    tree = ast.parse(expr, mode="eval")
    _check(tree)
    env = {
        k: float(v)
        for k, v in row.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    safe_builtins = {name: getattr(builtins, name) for name in _ALLOWED_CALLS}
    result = eval(compile(tree, "<formula>", "eval"), {"__builtins__": safe_builtins}, env)  # noqa: S307 - whitelisted AST
    return float(result)


def _normalize(expression: str) -> str:
    """``{col}`` → ``col`` so Python can parse it."""
    return _NAME_TOKEN.sub(r"\1", expression)


def _check(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"formula: {type(node).__name__} not allowed")
        if isinstance(node, ast.Name) and not node.id.isidentifier():
            raise ValueError(f"formula: bad name {node.id!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
                raise ValueError("formula: only round/abs/min/max calls allowed")


def recompute_formulas(
    row: dict[str, Any], columns: list[dict[str, Any]]
) -> dict[str, Any]:
    """Fill every formula column of ``row`` using other (non-formula) values.

    ``columns`` are catalog column dicts (with parsed ``config``). On an
    unresolved reference the cached value is left as ``None``.
    """
    result = dict(row)
    for col in columns:
        if col["type"] != "formula":
            continue
        expr = (col.get("config") or {}).get("expression", "")
        try:
            value = evaluate(expr, result)
        except (ValueError, SyntaxError, NameError, KeyError, ZeroDivisionError, TypeError):
            value = None
        result[col["key"]] = value
    return result
