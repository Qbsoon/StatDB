"""F2: dataset catalog — datasets CRUD, columns, types, physical tables, preset."""
from __future__ import annotations

import pytest

from app.catalog.types import COLUMN_TYPES, get_type


@pytest.fixture
async def catalog_db(tmp_path):
    from app.db import Database, run_migrations

    db = Database(tmp_path / "cat.db")
    await run_migrations(db)
    return db


async def test_create_dataset_alone(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("earnings", "Zarobki")
    assert ds["slug"] == "earnings"
    assert ds["columns"] == []
    # physical table exists
    row = await catalog_db.query_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = 'data_earnings'"
    )
    assert row is not None


async def test_dataset_name_unique_slug_conflict(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    await store.create_dataset("a", "A")
    with pytest.raises(ValueError, match="slug 'a' already exists"):
        await store.create_dataset("a", "Another")


async def test_add_column_all_types(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("full", "Full")
    for key in COLUMN_TYPES:
        cfg = {}
        if key == "select":
            cfg = {"options": [{"key": "a", "label": {"en": "A", "pl": "A"}}]}
        elif key == "currency":
            cfg = {"currency_code": "PLN"}
        # typ np. 'date-long' → klucz kolumny 'col_date_long' (identyfikator SQLite)
        col_key = f"col_{key}".replace("-", "_")
        col = await store.add_column(
            ds["id"], col_key, key.replace("_", " ").title(), key, cfg
        )
        assert col["key"] == col_key
        assert col["type"] == key
    cols = await store.get_columns(ds["id"])
    assert len(cols) == len(COLUMN_TYPES)


async def test_year_month_shadow_column(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("m", "M")
    await store.add_column(ds["id"], "month", "Miesiąc", "year-month", {"input_format": "MM-YYYY"})
    # physical table should have month TEXT + month__sort_key INTEGER
    tinfo = await catalog_db.query_all('PRAGMA table_info("data_m")')
    names = [r["name"] for r in tinfo]
    assert "month" in names
    assert "month__sort_key" in names
    type_map = {r["name"]: r["type"] for r in tinfo}
    assert type_map["month__sort_key"] == "INTEGER"


async def test_months_preset_generation(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_months_preset(2024, 2025)  # 2 years
    assert ds["slug"] == "months"
    cols = await store.get_columns(ds["id"])
    assert len(cols) == 1
    rows = await catalog_db.query_all('SELECT COUNT(*) AS n FROM "data_months"')
    assert rows[0]["n"] == 24


async def test_dataset_delete_cascades_physical(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("tmp", "Tmp")
    await store.delete_dataset(ds["id"])
    row = await catalog_db.query_one("SELECT name FROM sqlite_master WHERE name='data_tmp'")
    assert row is None


async def test_column_key_validation(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("x", "X")
    with pytest.raises(ValueError):
        await store.add_column(ds["id"], "1bad", "Bad", "text")
    with pytest.raises(ValueError):
        await store.add_column(ds["id"], "a-b", "Bad", "text")


async def test_unknown_type_rejected(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("z", "Z")
    with pytest.raises(KeyError):
        await store.add_column(ds["id"], "c", "C", "nonexistent_type")


async def test_column_delete_physical(catalog_db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(catalog_db)
    ds = await store.create_dataset("pd", "PD")
    col = await store.add_column(ds["id"], "v", "V", "integer")
    await store.remove_column(col["id"])
    tinfo = await catalog_db.query_all('PRAGMA table_info("data_pd")')
    names = [r["name"] for r in tinfo]
    assert "v" not in names
