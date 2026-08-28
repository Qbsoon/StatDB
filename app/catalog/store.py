"""Catalog repository: CRUD for datasets & columns, preset generator.

All writes to catalog tables go through this module; the physical table
managers in :mod:`app.catalog.migrations` are called when schema changes.
"""

from __future__ import annotations

import json
from typing import Any

from ..db import Database, row_to_dict
from . import migrations as phys
from .types import get_type

__all__ = ["CatalogStore", "row_to_dict"]


class CatalogStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------- datasets ----------

    async def create_dataset(self, slug: str, name: str, description: str = "") -> dict[str, Any]:
        slug = slug.strip()
        name = name.strip()
        if not slug:
            raise ValueError("Dataset slug required")
        if not name:
            raise ValueError("Dataset name required")
        # validate slug before any SQL
        phys.physical_table_name(slug)  # raises on bad slug
        exists = await self.get_dataset(slug=slug)
        if exists:
            raise ValueError(f"Dataset with slug '{slug}' already exists")

        dataset_id = await self.db.execute(
            "INSERT INTO datasets (slug, name, description) VALUES (?, ?, ?)",
            (slug, name, description),
        )
        await phys.create_physical_table(self.db, {"slug": slug}, [])
        return {
            "id": dataset_id,
            "slug": slug,
            "name": name,
            "description": description,
            "columns": [],
        }

    async def get_dataset(
        self, dataset_id: int | None = None, slug: str | None = None
    ) -> dict[str, Any] | None:
        if dataset_id is not None:
            row = await self.db.query_one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        elif slug is not None:
            row = await self.db.query_one("SELECT * FROM datasets WHERE slug = ?", (slug,))
        else:
            raise ValueError("Need dataset_id or slug")
        if not row:
            return None
        data = row_to_dict(row)
        data["columns"] = await self.get_columns(data["id"])
        return data

    async def list_datasets(self) -> list[dict[str, Any]]:
        rows = await self.db.query_all("SELECT * FROM datasets ORDER BY name")
        datasets = []
        for r in rows:
            d = row_to_dict(r)
            d["columns"] = await self.get_columns(d["id"])
            datasets.append(d)
        return datasets

    async def update_dataset(
        self, dataset_id: int, *, name: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        current = await self.get_dataset(dataset_id=dataset_id)
        if not current:
            raise KeyError(f"Dataset {dataset_id} not found")
        await self.db.execute(
            "UPDATE datasets SET name = ?, description = ? WHERE id = ?",
            (name or current["name"], description or current["description"], dataset_id),
        )
        return (await self.get_dataset(dataset_id=dataset_id)) or {}

    async def delete_dataset(self, dataset_id: int) -> None:
        dataset = await self.get_dataset(dataset_id=dataset_id)
        if dataset:
            await phys.drop_physical_table(self.db, dataset)
        await self.db.execute("DELETE FROM columns WHERE dataset_id = ?", (dataset_id,))
        await self.db.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))

    # ---------- columns ----------

    async def get_columns(self, dataset_id: int) -> list[dict[str, Any]]:
        rows = await self.db.query_all(
            "SELECT * FROM columns WHERE dataset_id = ? ORDER BY position, id", (dataset_id,)
        )
        return [self._column_meta(r) for r in rows]

    def _column_meta(self, row: dict[str, Any]) -> dict[str, Any]:
        data = row_to_dict(row)
        data["config"] = json.loads(data.get("config", "{}"))
        data["type_meta"] = {
            "label": get_type(data["type"]).label,
            "shadow_fields": get_type(data["type"]).shadow_fields,
        }
        return data

    async def add_column(
        self,
        dataset_id: int,
        key: str,
        label: str,
        type_key: str,
        config: dict[str, Any] | None = None,
        position: int | None = None,
    ) -> dict[str, Any]:
        dataset = await self.get_dataset(dataset_id=dataset_id)
        if not dataset:
            raise KeyError(f"Dataset {dataset_id} not found")
        get_type(type_key)  # validate type exists
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            raise ValueError(
                "Column key must start with a letter and contain only letters/digits/underscores"
            )
        if any(c["key"] == key for c in dataset["columns"]):
            raise ValueError(f"Column '{key}' already exists in dataset")

        if position is None:
            position = max((c["position"] for c in dataset["columns"]), default=0) + 1

        col_id = await self.db.execute(
            "INSERT INTO columns (dataset_id, key, label, type, config, position)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (dataset_id, key, label.strip(), type_key, json.dumps(config or {}), position),
        )
        # physical side
        await phys.add_physical_column(self.db, dataset, {"id": col_id, "key": key, "type": type_key, "position": position})
        return self._column_meta(
            await self.db.query_one("SELECT * FROM columns WHERE id = ?", (col_id,)) or {}
        )

    async def update_column(
        self, column_id: int, *, label: str | None = None, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        row = await self.db.query_one("SELECT * FROM columns WHERE id = ?", (column_id,))
        if not row:
            raise KeyError(f"Column {column_id} not found")
        await self.db.execute(
            "UPDATE columns SET label = ?, config = ? WHERE id = ?",
            (
                label or row["label"],
                json.dumps(config if config is not None else json.loads(row["config"])),
                column_id,
            ),
        )
        return self._column_meta(
            await self.db.query_one("SELECT * FROM columns WHERE id = ?", (column_id,)) or {}
        )

    async def remove_column(self, column_id: int) -> None:
        row = await self.db.query_one("SELECT * FROM columns WHERE id = ?", (column_id,))
        if not row:
            return
        dataset = await self.get_dataset(dataset_id=row["dataset_id"])
        if dataset:
            await phys.drop_physical_column(self.db, dataset, row_to_dict(row))
        await self.db.execute("UPDATE columns SET position = position - 1 WHERE dataset_id = ? AND position > (SELECT position FROM columns WHERE id = ?)", (row["dataset_id"], column_id))
        await self.db.execute("DELETE FROM columns WHERE id = ?", (column_id,))

    # ---------- preset "Miesiące" ----------

    async def create_months_preset(self, year_from: int = 2020, year_to: int = 2030) -> dict[str, Any]:
        """Generate a dataset 'months' with year-month values."""
        ds = await self.get_dataset(slug="months")
        if ds:
            return ds
        ds = await self.create_dataset("months", "Months", "Preset year-month axis")
        await self.add_column(
            ds["id"],
            key="month",
            label="Month",
            type_key="year-month",
            config={"input_format": "MM-YYYY"},
            position=1,
        )
        rows = []
        for y in range(year_from, year_to + 1):
            for m in range(1, 13):
                rows.append((f"{m:02d}-{y}", y * 100 + m))
        # insert into physical table directly (F3 will expose rows API)
        table = phys.physical_table_name(ds["slug"])
        async with self.db.connect() as conn:
            await conn.executemany(
                f'INSERT INTO "{table}" (month, "month__sort_key") VALUES (?, ?)', rows
            )
            await conn.commit()
        return ds
