"""Pure-SQL aggregation with logical→physical mapping and select ordering."""

from __future__ import annotations

from typing import Any

from ..catalog.migrations import physical_table_name
from ..catalog.types import option_label
from ..db import Database
from .filters import build_filters

AGG_SQL = {
    "sum": "SUM",
    "avg": "AVG",
    "count": "COUNT",
    "min": "MIN",
    "max": "MAX",
}
ALL_MEASURES = set(AGG_SQL) | {"median"}

MONTHS_PL = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
             "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"]


def months(lang: str) -> list[str]:
    return MONTHS_PL if lang == "pl" else MONTHS_EN


def _physical_pairs(col: dict[str, Any]) -> tuple[str, str]:
    """(display_expr, order_expr) for a column — year-month uses its shadow key."""
    key = f'"{col["key"]}"'
    order = f'"{col["key"]}__sort_key"' if col["type"] == "year-month" else key
    return key, order


async def aggregate(db: Database, dataset: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Run an aggregation request.

    Spec keys:
      measure   – aggregation: sum | avg | count | min | max | median (default sum)
      column    – measure column key (any numeric; default = count(*))
      group_by  – column key to bucket by (optional scalar result when omitted)
      series    – second key: each value becomes one output series
      filters   – see app.aggregation.filters
      lang      – "en" | "pl" (select label + month names)
    """
    columns = {c["key"]: c for c in dataset["columns"]}
    lang = spec.get("lang", "en")
    measure = spec.get("measure", "sum")
    if measure not in ALL_MEASURES:
        raise ValueError(f"bad measure '{measure}'")

    col_key = spec.get("column")
    group_key = spec.get("group_by")
    series_key = spec.get("series")
    filters = spec.get("filters")

    column_meta: dict[str, dict[str, Any]] = {}
    for key, col in columns.items():
        column_meta[key] = {
            "sql": key,
            "sort": f"{key}__sort_key" if col["type"] == "year-month" else None,
            "type": col["type"],
        }
    where_sql, params = build_filters(filters, column_meta)

    if measure not in ALL_MEASURES:
        raise ValueError(f"bad measure '{measure}'")
    if measure != "count" and col_key not in columns:
        raise ValueError(f"bad measure column '{col_key}'")
    if group_key and group_key not in columns:
        raise ValueError(f"bad group_by column '{group_key}'")
    if series_key and series_key not in columns:
        raise ValueError(f"bad series column '{series_key}'")

    table = physical_table_name(dataset["slug"])

    # --- median & total: plain SQL fetch, Python-side ---
    if measure == "median":
        col = f'"{col_key}"'
        base = f'SELECT {col} AS v FROM "{table}"{where_sql}'
        rows = await db.query_all(base, tuple(params))
        vals = sorted(r["v"] for r in rows if r["v"] is not None)
        n = len(vals)
        med = (vals[(n - 1) // 2] + vals[n // 2]) / 2 if n else None
        return {"kind": "scalar", "value": med, "measure": "median"}

    if measure == "count" and not col_key:
        measure_expr = "COUNT(*)"
    else:
        col = f'"{col_key}"'
        measure_expr = f"{AGG_SQL[measure]}({col})"

    select_parts = [f"{measure_expr} AS value"]
    groups: list[tuple[str, str, str]] = []  # (alias, display_expr, order_expr)
    if group_key:
        display, order = _physical_pairs(columns[group_key])
        select_parts += [f"{display} AS bucket", f"{order} AS bucket_sort"]
        groups.append(("bucket", display, order))
    if series_key:
        display, order = _physical_pairs(columns[series_key])
        select_parts += [f"{display} AS series", f"{order} AS series_sort"]
        groups.append(("series", display, order))

    sql = f'SELECT {", ".join(select_parts)} FROM "{table}"{where_sql}'
    if groups:
        sql += " GROUP BY " + ", ".join(g[0] for g in groups)
        sql += " ORDER BY " + ", ".join(g[2] for g in groups)

    rows = await db.query_all(sql, tuple(params))

    group_col = columns.get(group_key) if group_key else None
    series_col = columns.get(series_key) if series_key else None

    if not group_key:
        value = rows[0]["value"] if rows else None
        return {"kind": "scalar", "value": value, "measure": measure}

    buckets: dict[Any, dict[str, Any]] = {}
    series_order: dict[Any, Any] = {}
    series_labels: dict[Any, str] = {}
    for r in rows:
        bucket = r.get("bucket")
        value = r.get("value")
        series = r.get("series")
        if bucket not in buckets:
            buckets[bucket] = {
                "key": bucket,
                "sort": r.get("bucket_sort"),
                "label": _bucket_label(bucket, group_col, lang),
                "value": None,
                "series": {},
            }
        if series_key:
            if series not in series_order:
                series_order[series] = r.get("series_sort")
                series_labels[series] = _bucket_label(series, series_col, lang)
            buckets[bucket]["series"][series] = value
        else:
            buckets[bucket]["value"] = value

    group_rank = _rank_map(group_col)
    if group_rank is not None:
        ordered_buckets = sorted(
            buckets.values(),
            key=lambda b: (group_rank.get(b["key"], len(group_rank)), str(b["key"])),
        )
    else:
        ordered_buckets = sorted(
            buckets.values(),
            key=lambda b: (b["sort"] is None, b["sort"] if b["sort"] is not None else str(b["key"])),
        )
    series_rank = _rank_map(series_col)
    if series_rank is not None:
        series_list = sorted(
            series_order.items(),
            key=lambda kv: (series_rank.get(kv[0], len(series_rank)), str(kv[0])),
        )
    else:
        series_list = sorted(
            series_order.items(),
            key=lambda kv: (kv[1] is None, kv[1] if kv[1] is not None else str(kv[0])),
        )

    if series_key:
        return {
            "kind": "stacked",
            "measure": measure,
            "buckets": [
                {"key": b["key"], "label": b["label"], "sort": b["sort"]}
                for b in ordered_buckets
            ],
            "series": [
                {
                    "key": s,
                    "label": series_labels[s],
                    "color": _option_color(series_col, s),
                    "values": [b["series"].get(s) for b in ordered_buckets],
                }
                for s, _ in series_list
            ],
        }

    return {
        "kind": "grouped",
        "measure": measure,
        "items": [
            {"key": b["key"], "label": b["label"], "sort": b["sort"], "value": b["value"]}
            for b in ordered_buckets
        ],
    }


# ---------- label/color helpers ----------


def _rank_map(col: dict[str, Any] | None) -> dict[Any, int] | None:
    """Option-index order for select columns (todo §5: never alphabetical)."""
    if not col or col["type"] != "select":
        return None
    options = (col.get("config") or {}).get("options") or []
    return {opt.get("key"): idx for idx, opt in enumerate(options)}


def _bucket_label(bucket: Any, col: dict[str, Any] | None, lang: str) -> str:
    if col is None or bucket is None:
        return str(bucket)
    if col["type"] == "select":
        for opt in (col.get("config") or {}).get("options") or []:
            if opt.get("key") == bucket:
                return option_label(opt, lang)
        return str(bucket)
    return str(bucket)


def _option_color(col: dict[str, Any] | None, key: Any) -> str | None:
    if not col or col["type"] != "select":
        return None
    for opt in (col.get("config") or {}).get("options") or []:
        if opt.get("key") == key:
            return opt.get("color")
    return None
