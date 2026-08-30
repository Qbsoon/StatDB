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
      group_by  – column key, or a LIST of keys (e.g. ["year", "month"]) for a
                  composite bucket axis — timeline "month over year" (todo §15.12)
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
    raw_group = spec.get("group_by")
    if raw_group is None:
        group_keys: list[str] = []
    elif isinstance(raw_group, (list, tuple)):
        group_keys = [str(k) for k in raw_group if k]
    else:
        group_keys = [str(raw_group)] if str(raw_group) else []
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
    for gk in group_keys:
        if gk not in columns:
            raise ValueError(f"bad group_by column '{gk}'")
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
    for i, gk in enumerate(group_keys):
        display, order = _physical_pairs(columns[gk])
        select_parts += [f"{display} AS g{i}", f"{order} AS g{i}_sort"]
    if series_key:
        display, order = _physical_pairs(columns[series_key])
        select_parts += [f"{display} AS series", f"{order} AS series_sort"]

    sql = f'SELECT {", ".join(select_parts)} FROM "{table}"{where_sql}'
    group_terms = [f"g{i}" for i in range(len(group_keys))]
    order_terms = [f"g{i}_sort" for i in range(len(group_keys))]
    if series_key:
        group_terms.append("series")
        order_terms.append("series_sort")
    if group_terms:
        sql += " GROUP BY " + ", ".join(group_terms)
        sql += " ORDER BY " + ", ".join(order_terms)

    rows = await db.query_all(sql, tuple(params))

    group_cols = [columns[gk] for gk in group_keys]
    group_ranks = [_rank_map(c) for c in group_cols]
    series_col = columns.get(series_key) if series_key else None

    if not group_keys:
        value = rows[0]["value"] if rows else None
        return {"kind": "scalar", "value": value, "measure": measure}

    def _bucket_key_repr(vals: tuple) -> Any:
        return vals[0] if len(vals) == 1 else " ".join(str(v) for v in vals)

    def _bucket_label(vals: tuple) -> str:
        if len(vals) == 1:
            return _bucket_label_single(vals[0], group_cols[0], lang)
        return " ".join(
            _bucket_label_single(v, c, lang) for v, c in zip(vals, group_cols)
        )

    buckets: dict[tuple, dict[str, Any]] = {}
    series_order: dict[Any, Any] = {}
    series_labels: dict[Any, str] = {}
    for r in rows:
        vals = tuple(r.get(f"g{i}") for i in range(len(group_keys)))
        sorts = tuple(r.get(f"g{i}_sort") for i in range(len(group_keys)))
        if vals not in buckets:
            buckets[vals] = {
                "vals": vals,
                "sorts": sorts,
                "key": _bucket_key_repr(vals),
                "label": _bucket_label(vals),
                "sort": sorts[0] if len(sorts) == 1 else list(sorts),
                "value": None,
                "series": {},
            }
        bucket = buckets[vals]
        value = r.get("value")
        series = r.get("series")
        if series_key:
            if series not in series_order:
                series_order[series] = r.get("series_sort")
                series_labels[series] = _bucket_label_single(series, series_col, lang)
            bucket["series"][series] = value
        else:
            bucket["value"] = value

    def _bucket_order(b: dict[str, Any]) -> tuple:
        sk: list[Any] = []
        for i, col in enumerate(group_cols):
            rank = group_ranks[i]
            v = b["vals"][i]
            if rank is not None:
                sk.append((rank.get(v, len(rank)), str(v)))
            else:
                sv = b["sorts"][i]
                sk.append((sv is None, sv if sv is not None else str(v)))
        return tuple(sk)

    ordered_buckets = sorted(buckets.values(), key=_bucket_order)
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


def _bucket_label_single(bucket: Any, col: dict[str, Any] | None, lang: str) -> str:
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
