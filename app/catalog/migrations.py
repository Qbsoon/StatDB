"""Physical table management for datasets.

Datasets are logical objects in the catalog; every one owns a physical
``data_<slug>`` table in SQLite. Columns map to physical columns plus
optional shadow fields (sort_key for year-month etc.).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import aiosqlite

from ..db import Database
from .types import get_type

if TYPE_CHECKING:
    pass

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DATA_TABLE_PREFIX = "data_"


def physical_table_name(slug: str) -> str:
    """Map dataset slug to its physical table name."""
    if not SLUG_RE.match(slug):
        raise ValueError(f"Invalid dataset slug: {slug}")
    return f"{DATA_TABLE_PREFIX}{slug}"


def _column_ddl(col_key: str, type_key: str, position: int) -> list[str]:
    """Generate physical column DDL(s) for one logical column.

    Returns list of SQL fragments like ["amount REAL", "month TEXT"] or
    extra shadow fields for sortable types.
    """
    col = get_type(type_key)
    field_name = col_key
    ddl = [f'"{field_name}" {col.sqlite_type}']
    for shadow in col.shadow_fields:
        if shadow == "sort_key":
            ddl.append(f'"{field_name}__sort_key" INTEGER')
    return ddl


async def create_physical_table(db: Database, dataset: dict[str, Any], columns: list[dict[str, Any]]) -> None:
    """Create ``data_<slug>`` with base metadata fields + logical columns."""
    table = physical_table_name(dataset["slug"])
    fields = [
        '"id" INTEGER PRIMARY KEY AUTOINCREMENT',
        '"created_at" TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%fZ\', \'now\'))',
        '"updated_at" TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%fZ\', \'now\'))',
    ]
    for col in sorted(columns, key=lambda c: c["position"]):
        fields.extend(_column_ddl(col["key"], col["type"], col["position"]))

    ddl = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(fields)})'
    async with db.connect() as conn:
        await conn.execute(ddl)
        await conn.commit()


async def drop_physical_table(db: Database, dataset: dict[str, Any]) -> None:
    """Remove physical table when dataset is deleted."""
    table = physical_table_name(dataset["slug"])
    async with db.connect() as conn:
        await conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        await conn.commit()


async def add_physical_column(db: Database, dataset: dict[str, Any], column: dict[str, Any]) -> None:
    """ALTER TABLE ADD COLUMN for a new logical column."""
    table = physical_table_name(dataset["slug"])
    fragments = _column_ddl(column["key"], column["type"], column["position"])
    async with db.connect() as conn:
        for frag in fragments:
            await conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {frag}')
        await conn.commit()


async def drop_physical_column(db: Database, dataset: dict[str, Any], column: dict[str, Any]) -> None:
    """SQLite ≥3.35 supports DROP COLUMN; we require it."""
    table = physical_table_name(dataset["slug"])
    fragments = _column_ddl(column["key"], column["type"], column["position"])
    async with db.connect() as conn:
        for frag in fragments:
            field_name = frag.split(" ", 1)[0].strip('"')
            await conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{field_name}"')
        await conn.commit()
