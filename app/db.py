"""SQLite data layer: aiosqlite wrapper + catalog schema migrations.

One short-lived connection per call keeps the design simple and robust; each
connection gets foreign keys and WAL enabled. All query accessors in later
phases (catalog/, rows/, …) accept the ``Database`` from app extensions, never
build connections themselves.
"""

from __future__ import annotations

import logging
import re
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

import aiosqlite

log = logging.getLogger(__name__)


def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an aiosqlite/sqlite Row (or plain dict) to a plain dict."""
    if isinstance(row, dict):
        return row
    return dict(row)


USER_VERSION = 2  # bump whenever a new migration file is added
MIGRATION_DIR = "migrations"
_MIGRATION_NAME_RE = re.compile(r"^(\d+)_.+\.sql$")

_BASE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
)


class Database:
    """Thin async wrapper around a path to a SQLite database file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> aiosqlite.Connection:
        """Return a fresh, not-yet-started connection handle.

        aiosqlite starts the connection's worker thread the **first time the
        object is awaited** — ``async with db.connect() as conn:`` awaits it
        exactly once (in ``__aenter__``), so never ``await`` the handle
        beforehand. Row factory and pragmas must be applied **inside** the
        block (see :meth:`_prepare`), where the real sqlite3 connection
        already exists.
        """
        return aiosqlite.connect(str(self.path))

    async def _prepare(self, conn: aiosqlite.Connection) -> None:
        """Apply Row factory + base pragmas to an already-open connection."""
        conn.row_factory = aiosqlite.Row
        for pragma in _BASE_PRAGMAS:
            await conn.execute(pragma)

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run one statement, return lastrowid."""
        async with self.connect() as conn:
            await self._prepare(conn)
            cur = await conn.execute(sql, tuple(params))
            await conn.commit()
            return cur.lastrowid or 0

    async def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        async with self.connect() as conn:
            await self._prepare(conn)
            cur = await conn.execute(sql, tuple(params))
            row = await cur.fetchone()
            return dict(row) if row is not None else None

    async def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        async with self.connect() as conn:
            await self._prepare(conn)
            cur = await conn.execute(sql, tuple(params))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def quick_check(self) -> None:
        """Cheap liveness probe used by /healthz."""
        async with self.connect() as conn:
            await conn.execute("SELECT 1")


def _load_migrations() -> list[tuple[int, str]]:
    """Read bundled ``NNN_*.sql`` files, ordered by version."""
    migrations: list[tuple[int, str]] = []
    for entry in resources.files(f"app.{MIGRATION_DIR}").iterdir():
        match = _MIGRATION_NAME_RE.match(entry.name)
        if match:
            sql = entry.read_text(encoding="utf-8")
            migrations.append((int(match.group(1)), sql))
    migrations.sort(key=lambda item: item[0])
    versions = [v for v, _ in migrations]
    assert versions == list(range(1, len(versions) + 1)), (
        f"Migration versions must be 1..N without gaps, got {versions}"
    )
    return migrations


async def run_migrations(db: Database) -> list[int]:
    """Create pragma/track table, upgrade to the newest catalog schema.

    Returns the list of versions applied during *this* call.
    """
    db.path.parent.mkdir(parents=True, exist_ok=True)
    applied_now: list[int] = []
    migrations = _load_migrations()

    async with db.connect() as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
        )
        cur = await conn.execute("PRAGMA user_version")
        current = (await cur.fetchone())[0]

        for version, sql in migrations:
            if version <= current:
                continue
            log.info("Applying migration %03d", version)
            await conn.executescript(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            await conn.execute(f"PRAGMA user_version = {version}")
            await conn.commit()
            applied_now.append(version)

    if applied_now:
        log.info("Database at schema version %d", applied_now[-1])
    return applied_now


def init_app(app) -> None:
    """Attach the Database to the app and migrate before the first request."""
    cfg = app.config["STATDB"]
    db = Database(cfg.db_path)
    app.extensions["db"] = db

    @app.before_serving
    async def _migrate() -> None:  # type: ignore[misc]
        applied = await run_migrations(db)
        if applied:
            app.logger.info("Catalog schema ready (applied: %s)", applied)


def get_db() -> Database:
    """Convenience accessor, usable from any request/task context."""
    from quart import current_app

    return current_app.extensions["db"]
