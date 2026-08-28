"""Row-level CRUD against physical ``data_<slug>`` tables.

Validates each payload against column types, fills shadow fields
(``<key>__sort_key``), recomputes formula columns and supports filtering
+ pagination for list queries.
"""

from __future__ import annotations

from typing import Any

from ..catalog.migrations import physical_table_name
from ..db import Database, row_to_dict
from .formula import recompute_formulas
from .validators import VALIDATORS


def _ops() -> dict[str, str]:
    return {
        "eq": "=",
        "ne": "!=",
        "lt": "<",
        "lte": "<=",
        "gt": ">",
        "gte": ">=",
        "contains": "LIKE",
    }


class RowStore:
    SYS_FIELDS = {"id", "created_at", "updated_at"}

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_row(
        self,
        dataset: dict[str, Any],
        values: dict[str, Any],
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        columns = dataset["columns"]
        by_key = {c["key"]: c for c in columns}
        unknown = set(values) - set(by_key)
        if strict and unknown:
            raise ValueError(f"unknown column keys: {sorted(unknown)}")

        physical: dict[str, Any] = {}
        for key, col in by_key.items():
            if key not in values:
                continue
            self._write_value(physical, col, values[key])

        # formula recompute needs input values by logical key
        merged = {c["key"]: physical.get(c["key"]) for c in columns if c["key"] in physical}
        merged = recompute_formulas(merged, columns)
        for col in columns:
            if col["type"] == "formula" and col["key"] in merged:
                physical[col["key"]] = merged[col["key"]]

        table = physical_table_name(dataset["slug"])
        cols = list(physical.keys()) or []
        if cols:
            placeholders = ", ".join("?" for _ in cols)
            quoted = ", ".join(f'"{c}"' for c in cols)
            sql = f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})'
            row_id = await self.db.execute(sql, tuple(physical[c] for c in cols))
        else:
            row_id = await self.db.execute(f'INSERT INTO "{table}" DEFAULT VALUES')
        return (await self.get_row(dataset, row_id)) or {}

    async def get_row(self, dataset: dict[str, Any], row_id: int) -> dict[str, Any] | None:
        table = physical_table_name(dataset["slug"])
        row = await self.db.query_one(f'SELECT * FROM "{table}" WHERE id = ?', (row_id,))
        return row_to_dict(row) if row else None

    async def update_row(
        self,
        dataset: dict[str, Any],
        row_id: int,
        values: dict[str, Any],
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        existing = await self.get_row(dataset, row_id)
        if existing is None:
            raise KeyError(f"row {row_id} not found")
        columns = dataset["columns"]
        by_key = {c["key"]: c for c in columns}
        unknown = set(values) - set(by_key)
        if strict and unknown:
            raise ValueError(f"unknown column keys: {sorted(unknown)}")

        physical: dict[str, Any] = {}
        for key, col in by_key.items():
            if key not in values:
                continue
            self._write_value(physical, col, values[key])

        merged = {c["key"]: existing.get(c["key"]) for c in columns}
        for k, v in physical.items():
            if k in merged:
                merged[k] = v
        for col in columns:  # refresh shadow inputs too
            if col["type"] == "year-month" and col["key"] in physical:
                merged[col["key"]] = physical[col["key"]]
        merged = recompute_formulas(merged, columns)
        for col in columns:
            if col["type"] == "formula":
                physical[col["key"]] = merged[col["key"]]

        table = physical_table_name(dataset["slug"])
        assignments = [f'"{k}" = ?' for k in physical]
        assignments.append('"updated_at" = strftime(\'%Y-%m-%dT%H:%M:%fZ\', \'now\')')
        params = tuple(physical.values()) + (row_id,)
        await self.db.execute(
            f'UPDATE "{table}" SET {", ".join(assignments)} WHERE id = ?', params
        )
        return (await self.get_row(dataset, row_id)) or {}

    async def delete_row(self, dataset: dict[str, Any], row_id: int) -> bool:
        table = physical_table_name(dataset["slug"])
        async with self.db.connect() as conn:
            cur = await conn.execute(f'DELETE FROM "{table}" WHERE id = ?', (row_id,))
            await conn.commit()
            return cur.rowcount > 0

    async def list_rows(
        self,
        dataset: dict[str, Any],
        page: int = 1,
        page_size: int = 50,
        filters: dict[str, dict[str, Any]] | None = None,
        sort: str | None = None,
    ) -> dict[str, Any]:
        if page < 1 or not (1 <= page_size <= 500):
            raise ValueError("invalid page/page_size")
        columns = dataset["columns"]
        by_key = {c["key"]: c for c in columns}
        physical_name = {
            c["key"]: f'{c["key"]}__sort_key' if c["type"] == "year-month" else c["key"]
            for c in columns
        }
        table = physical_table_name(dataset["slug"])
        ops = _ops()
        where: list[str] = []
        params: list[Any] = []
        for key, clause in (filters or {}).items():
            if key not in by_key:
                raise ValueError(f"cannot filter by unknown key '{key}'")
            physical_col = physical_name[key]
            for op, value in clause.items():
                if op not in ops:
                    raise ValueError(f"bad operator '{op}'")
                if op == "contains":
                    where.append(f'"{physical_col}" LIKE ?')
                    params.append(f"%{value}%")
                else:
                    where.append(f'"{physical_col}" {ops[op]} ?')
                    params.append(value)
        where_sql = f" WHERE {' AND '.join(where)}" if where else ""

        order_sql = ""
        if sort:
            desc = sort.startswith("-")
            key = sort.lstrip("+-")
            if key not in by_key and key not in self.SYS_FIELDS:
                raise ValueError(f"cannot sort by unknown key '{key}'")
            physical_col = physical_name.get(key, key)
            order_sql = f' ORDER BY "{physical_col}" {"DESC" if desc else "ASC"}, "id" ASC'

        total = (
            await self.db.query_one(f'SELECT COUNT(*) AS c FROM "{table}"{where_sql}', tuple(params))
            or {"c": 0}
        )["c"]
        rows = await self.db.query_all(
            f'SELECT * FROM "{table}"{where_sql}{order_sql} LIMIT ? OFFSET ?',
            tuple(params) + (page_size, (page - 1) * page_size),
        )
        items = [row_to_dict(r) for r in rows]
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def _write_value(self, physical: dict[str, Any], col: dict[str, Any], raw: Any) -> None:
        key, type_key, config = col["key"], col["type"], col.get("config") or {}
        if raw is None:
            physical[key] = None
            if type_key == "year-month":
                physical[f"{key}__sort_key"] = None
            return
        validator = VALIDATORS[type_key]
        if type_key == "year-month":
            normalized, sort_key = validator(raw, config)
            physical[key] = normalized
            physical[f"{key}__sort_key"] = sort_key
        else:
            physical[key] = validator(raw, config)
