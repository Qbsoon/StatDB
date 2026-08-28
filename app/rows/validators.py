"""Per-type Python-side validation of row values before they hit SQLite.

Each validator returns a normalized value (e.g. ISO string for dates,
int 0/1 for bools) or raises ``ValueError`` with a readable message.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

YM_RE = re.compile(r"^(0?[1-9]|1[0-2])[-.](\d{4})$")
YM_PATCHED = re.compile(r"^(0[1-9]|1[0-2])-(\d{4})$")


def validate_text(value: Any, config: dict[str, Any]) -> str:
    if not isinstance(value, str):
        raise ValueError("text must be a string")
    max_len = (config or {}).get("max_length")
    if max_len and len(value) > int(max_len):
        raise ValueError(f"text exceeds max_length {max_len}")
    return value


def validate_integer(value: Any, config: dict[str, Any]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        # accept "42"-like numeric strings? keep strict — UI sends real ints
        raise ValueError("integer must be an int")
    return value


def validate_float(value: Any, config: dict[str, Any]) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("float must be a number")
    return float(value)


def validate_bool(value: Any, config: dict[str, Any]) -> int:
    if not isinstance(value, bool):
        raise ValueError("bool must be true/false")
    return 1 if value else 0


def validate_date(value: Any, config: dict[str, Any]) -> str:
    if not isinstance(value, str):
        raise ValueError("date must be 'YYYY-MM-DD'")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("date must be 'YYYY-MM-DD'") from None
    return parsed.isoformat()


def validate_date_long(value: Any, config: dict[str, Any]) -> str:
    # physical ISO; UI renders long/wordy month
    return validate_date(value, config)


def validate_datetime(value: Any, config: dict[str, Any]) -> str:
    if not isinstance(value, str):
        raise ValueError("datetime must be ISO 'YYYY-MM-DDTHH:MM[:SS]'")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("datetime must be ISO 'YYYY-MM-DDTHH:MM[:SS]'") from None
    return parsed.replace(microsecond=0).isoformat()


def validate_year(value: Any, config: dict[str, Any]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("year must be an integer, e.g. 2026")
    if not 0 <= value <= 9999:
        raise ValueError("year out of range 0..9999")
    return value


def validate_year_month(value: Any, config: dict[str, Any]) -> tuple[str, int]:
    """Validate 'MM-YYYY' (or config 'MM.YYYY') → (normalized 'MM-YYYY', sort_key)."""
    if not isinstance(value, str):
        raise ValueError("year-month must be 'MM-YYYY'")
    fmt = (config or {}).get("input_format", "MM-YYYY")
    expected_sep = "." if fmt == "MM.YYYY" else "-"
    m = YM_RE.match(value.strip())
    if not m:
        raise ValueError(f"year-month must match {fmt}")
    month, year = int(m.group(1)), int(m.group(2))
    if expected_sep not in value:
        raise ValueError(f"year-month must use separator '{expected_sep}' per column config")
    return f"{month:02d}-{year}", year * 100 + month


def validate_select(value: Any, config: dict[str, Any]) -> str:
    if not isinstance(value, str):
        raise ValueError("select must be a string key")
    options = (config or {}).get("options") or []
    keys = {o.get("key") for o in options}
    if not options:
        raise ValueError("select column has no options configured")
    if value not in keys:
        raise ValueError(f"select value must be one of: {sorted(keys)}")
    return value


def validate_currency(value: Any, config: dict[str, Any]) -> float:
    return validate_float(value, config)  # currency_code lives in column config


def validate_formula(value: Any, config: dict[str, Any]) -> float | None:
    # Usually None/unset: engine recomputes. Explicit value allowed (REAL).
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("formula value must be numeric (or omitted)")
    return float(value)


VALIDATORS = {
    "text": validate_text,
    "integer": validate_integer,
    "float": validate_float,
    "bool": validate_bool,
    "date": validate_date,
    "date-long": validate_date_long,
    "datetime": validate_datetime,
    "year": validate_year,
    "year-month": validate_year_month,
    "select": validate_select,
    "currency": validate_currency,
    "formula": validate_formula,
}
