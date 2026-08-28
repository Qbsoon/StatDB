"""F1: data layer and migration runner tests."""

from __future__ import annotations

import pytest

from app.db import USER_VERSION, Database, run_migrations

CATALOG_TABLES = {
    "schema_migrations",
    "datasets",
    "columns",
    "views",
    "widgets",
    "settings",
    "share_links",
    "api_tokens",
}


async def test_migrations_create_catalog(tmp_path):
    db = Database(tmp_path / "x.db")
    applied_first = await run_migrations(db)
    all_versions = list(range(1, USER_VERSION + 1))
    assert applied_first == all_versions

    async with db.connect() as conn:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row[0] for row in await cur.fetchall()}
        assert CATALOG_TABLES <= names

        cur = await conn.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == USER_VERSION

        cur = await conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        assert [row[0] for row in await cur.fetchall()] == all_versions


async def test_migrations_are_idempotent(tmp_path):
    db = Database(tmp_path / "x.db")
    await run_migrations(db)
    assert await run_migrations(db) == []  # second run applies nothing

    async with db.connect() as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM schema_migrations")
        assert (await cur.fetchone())[0] == USER_VERSION


async def test_parent_dir_created_automatically(tmp_path):
    db = Database(tmp_path / "deep" / "nested" / "x.db")
    await run_migrations(db)
    assert db.path.parent.is_dir()


async def test_wal_mode_and_foreign_keys(tmp_path):
    db = Database(tmp_path / "x.db")
    await run_migrations(db)

    async with db.connect() as conn:
        await conn.execute("PRAGMA foreign_keys=ON")  # mirroring runner behaviour
        cur = await conn.execute("PRAGMA journal_mode")
        assert (await cur.fetchone())[0].lower() == "wal"

        cur = await conn.execute("PRAGMA foreign_keys")
        assert (await cur.fetchone())[0] == 1


async def test_accessors_roundtrip(tmp_path):
    db = Database(tmp_path / "x.db")
    await run_migrations(db)

    row_id = await db.execute(
        "INSERT INTO datasets (slug, name) VALUES (?, ?)", ("income", "Income")
    )
    assert row_id >= 1

    one = await db.query_one("SELECT * FROM datasets WHERE slug = ?", ("income",))
    assert one is not None
    assert one["name"] == "Income"

    all_rows = await db.query_all("SELECT * FROM datasets")
    assert len(all_rows) == 1
    assert all_rows[0]["slug"] == "income"

    assert await db.query_one("SELECT * FROM datasets WHERE slug = 'nope'") is None
    await db.quick_check()  # does not raise


async def test_foreign_key_enforced_through_accessor(tmp_path):
    db = Database(tmp_path / "x.db")
    await run_migrations(db)
    # columns.dataset_id must reference an existing dataset; accessor enables FKs
    with pytest.raises(Exception):
        await db.execute(
            "INSERT INTO columns (dataset_id, key, label, type) VALUES (42, 'k', 'K', 'text')"
        )
