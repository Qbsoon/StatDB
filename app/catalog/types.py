"""Column type definitions: logical (UI) → physical (SQLite) mapping.

Every logical column in a dataset gets a physical counterpart in the
dynamic ``data_<slug>`` table. Types that need secondary guarantees
(like sortable year-month) generate extra *shadow* fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ColumnType:
    key: str                # ui key, e.g. "year-month"
    label: dict[str, str]   # en/pl labels
    sqlite_type: str        # TEXT | INTEGER | REAL
    config_schema: dict[str, Any]  # json-schema-ish for validation
    shadow_fields: list[str] = field(default_factory=list)  # extra columns to create


COLUMN_TYPES: dict[str, ColumnType] = {
    "text": ColumnType(
        "text",
        {"en": "Text", "pl": "Tekst"},
        "TEXT",
        {"type": "object", "properties": {"max_length": {"type": "integer", "minimum": 1}}},
    ),
    "integer": ColumnType(
        "integer",
        {"en": "Integer", "pl": "Liczba całkowita"},
        "INTEGER",
        {"type": "object"},
    ),
    "float": ColumnType(
        "float",
        {"en": "Decimal", "pl": "Liczba dziesiętna"},
        "REAL",
        {"type": "object", "properties": {"precision": {"type": "integer", "minimum": 0, "maximum": 10}}},
    ),
    "bool": ColumnType(
        "bool",
        {"en": "Boolean", "pl": "Tak/Nie"},
        "INTEGER",
        {"type": "object"},
    ),
    "date": ColumnType(
        "date",
        {"en": "Date (short)", "pl": "Data (krótka)"},
        "TEXT",
        {"type": "object"},  # stored as ISO YYYY-MM-DD
    ),
    "date-long": ColumnType(
        "date-long",
        {"en": "Date (long)", "pl": "Data (słowna)"},
        "TEXT",
        {"type": "object"},  # ISO; UI localises month name
    ),
    "datetime": ColumnType(
        "datetime",
        {"en": "Date & time", "pl": "Data i godzina"},
        "TEXT",
        {"type": "object"},  # ISO YYYY-MM-DDTHH:MM:SS
    ),
    "year": ColumnType(
        "year",
        {"en": "Year", "pl": "Rok"},
        "INTEGER",
        {"type": "object"},
    ),
    "year-month": ColumnType(
        "year-month",
        {"en": "Year-month", "pl": "Rok-miesiąc"},
        "TEXT",
        {
            "type": "object",
            "properties": {"input_format": {"type": "string", "enum": ["MM-YYYY", "MM.YYYY"]}},
        },
        shadow_fields=["sort_key"],  # physical column <key>__sort_key INTEGER
    ),
    "select": ColumnType(
        "select",
        {"en": "Select", "pl": "Lista wyboru"},
        "TEXT",
        {
            "type": "object",
            "required": ["options"],
            "properties": {
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "label": {"type": "object"},  # {"en": "…", "pl": "…"}
                            "color": {"type": "string"},
                        },
                        "required": ["key", "label"],
                    },
                },
            },
        },
    ),
    "currency": ColumnType(
        "currency",
        {"en": "Currency", "pl": "Waluta"},
        "REAL",
        {
            "type": "object",
            "properties": {"currency_code": {"type": "string", "minLength": 3, "maxLength": 3}},
            "required": ["currency_code"],
        },
    ),
    "formula": ColumnType(
        "formula",
        {"en": "Formula", "pl": "Formuła"},
        "REAL",  # result cached in DB; recomputed on row write
        {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
    ),
}

def get_type(key: str) -> ColumnType:
    if key not in COLUMN_TYPES:
        raise KeyError(f"Unknown column type: {key}")
    return COLUMN_TYPES[key]


def option_label(opt: dict, lang: str = "en") -> str:
    """Resolve the display label for a select option.

    Supports two label formats:
      * ``label`` as a plain string  → returned directly
      * ``label`` as a mapping ``{"en": ..., "pl": ...}`` → resolved by lang
    Falls back to the option ``key`` when no label is available.
    """
    label = opt.get("label")
    if isinstance(label, str):
        return label
    if isinstance(label, dict):
        return str(label.get(lang) or label.get("en") or opt.get("key") or "")
    return str(opt.get("key") or "")
