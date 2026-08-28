"""Filter compilation for the aggregation engine.

Shared ops with the rows API (eq/ne/lt/lte/gt/gte/contains) + `in`/`year`.
``columns`` maps a logical key to ``{"sql", "sort", "type"}`` where
``sort`` is the physical ``<key>__sort_key`` shadow of year-month columns
(else None). Year-month comparisons run on the numeric shadow with values
normalized to YYYYMM; ``contains`` matches on the display text.
"""

from __future__ import annotations

from typing import Any

OPS_SQL = {
    "eq": "=",
    "ne": "!=",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
    "contains": "LIKE",
}


def _ym_sort_key(value: Any) -> int:
    """'MM-YYYY' → YYYYMM int ('YYYY-MM' accepted too)."""
    parts = str(value).strip().split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"bad year-month filter value '{value}'")
    a, b = int(parts[0]), int(parts[1])
    month, year = (a, b) if len(parts[1]) == 4 else (b, a)
    if not 1 <= month <= 12:
        raise ValueError(f"bad year-month filter value '{value}'")
    return year * 100 + month


def build_filters(
    filters: dict[str, dict[str, Any]] | list[dict[str, Any]] | None,
    columns: dict[str, dict[str, Any]],
) -> tuple[str, list[Any]]:
    """Compile filters into a WHERE fragment + params.

    ``filters`` formats accepted (dict or list of clauses):
      {"kind": {"eq": "invoice"}, "amount": {"gte": 100}}
      [{"column": "kind", "op": "eq", "value": "invoice"}, …]
    ``columns`` maps logical key → {"sql": display name, "sort": shadow or
    None, "type": catalog type}; every filterable key must be present.
    """
    if not filters:
        return "", []
    clauses: list[dict[str, Any]] = []
    if isinstance(filters, dict):
        for key, ops in filters.items():
            for op, value in ops.items():
                clauses.append({"column": key, "op": op, "value": value})
    else:
        clauses = list(filters)

    where: list[str] = []
    params: list[Any] = []
    for clause in clauses:
        key = clause.get("column")
        op = clause.get("op")
        value = clause.get("value")
        meta = columns.get(key or "")
        if meta is None:
            raise ValueError(f"unknown filter column '{key}'")
        base = f'"{meta["sql"]}"'
        shadow = f'"{meta["sort"]}"' if meta.get("sort") else None
        ym = meta.get("type") == "year-month" and shadow is not None
        target = shadow if ym else base

        if op == "contains":
            where.append(f"{base} LIKE ?")
            params.append(f"%{value}%")
        elif op in OPS_SQL:
            where.append(f"{target} {OPS_SQL[op]} ?")
            params.append(_ym_sort_key(value) if ym else value)
        elif op == "in":
            items = value if isinstance(value, (list, tuple)) else [value]
            if not items:
                raise ValueError("'in' needs at least one value")
            where.append(f"{target} IN ({', '.join('?' for _ in items)})")
            params.extend(_ym_sort_key(v) if ym else v for v in items)
        elif op == "year":
            # works for date / datetime / year / year-month columns (TEXT/INT)
            where.append(f"CAST(substr(CAST({target} AS TEXT), 1, 4) AS INTEGER) = ?")
            params.append(int(value))
        else:
            raise ValueError(f"bad filter operator '{op}'")
    sql = f" WHERE {' AND '.join(where)}" if where else ""
    return sql, params
