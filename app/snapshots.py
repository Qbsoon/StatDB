"""F10 — Scheduled database snapshots with retention.

A lightweight asyncio background task that periodically copies the SQLite
database (via VACUUM INTO) into ``data/snapshots/`` and prunes old copies
to respect the retention policy.

Configuration (env vars):
  STATDB_SNAPSHOT_INTERVAL   seconds between snapshots (default 86400 = 24h)
  STATDB_SNAPSHOT_RETENTION  number of snapshots to keep (default 7)
  STATDB_SNAPSHOT_ENABLED    "1"/"true"/"on" to enable (default disabled)
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database

log = logging.getLogger(__name__)

_SNAP_DIR = "snapshots"
_SNAP_RE = re.compile(r"^statdb-snapshot-(\d{8}T\d{6}Z)\.db$")
_DEFAULT_INTERVAL = 86400       # 24h
_DEFAULT_RETENTION = 7

_task: asyncio.Task | None = None


def snapshot_dir(cfg: Config) -> Path:
    return cfg.data_dir / _SNAP_DIR


def _resolve_interval(cfg: Config) -> int:
    import os
    raw = os.environ.get("STATDB_SNAPSHOT_INTERVAL")
    if raw:
        try:
            return max(int(raw), 60)
        except ValueError:
            pass
    return _DEFAULT_INTERVAL


def _resolve_retention(cfg: Config) -> int:
    import os
    raw = os.environ.get("STATDB_SNAPSHOT_RETENTION")
    if raw:
        try:
            return max(int(raw), 1)
        except ValueError:
            pass
    return _DEFAULT_RETENTION


def _is_enabled(cfg: Config) -> bool:
    import os
    raw = os.environ.get("STATDB_SNAPSHOT_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


async def create_snapshot(cfg: Config | None = None) -> dict[str, Any] | None:
    """Create one snapshot now. Returns metadata dict or None if disabled."""
    if cfg is None:
        cfg = __import__("quart").current_app.config["STATDB"]
    d = snapshot_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"statdb-snapshot-{ts}.db"
    import sqlite3, asyncio
    def _do_vacuum(src, dst):
        conn = sqlite3.connect(str(src), isolation_level=None)
        try:
            conn.execute(f"VACUUM INTO '{dst}'")
        finally:
            conn.close()
    await asyncio.to_thread(_do_vacuum, cfg.db_path, path)
    size = path.stat().st_size
    log.info("Snapshot created: %s (%d bytes)", path.name, size)
    _prune_snapshots(cfg)
    return {"name": path.name, "size": size, "created_at": ts}


def _cfg_or_app(cfg: Config | None = None) -> Config:
    if cfg is not None:
        return cfg
    return __import__("quart").current_app.config["STATDB"]


def list_snapshot_files(cfg: Config | None = None) -> list[dict[str, Any]]:
    """Return sorted (newest first) snapshot metadata."""
    cfg = _cfg_or_app(cfg)
    d = snapshot_dir(cfg)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir(), reverse=True):
        m = _SNAP_RE.match(f.name)
        if m:
            out.append({
                "name": f.name,
                "size": f.stat().st_size,
                "created_at": m.group(1),
            })
    return out


def delete_snapshot_file(name: str, cfg: Config | None = None) -> bool:
    """Delete one snapshot by filename. Returns True if deleted."""
    cfg = _cfg_or_app(cfg)
    if not _SNAP_RE.match(name):
        return False
    path = snapshot_dir(cfg) / name
    if not path.is_file():
        return False
    path.unlink()
    return True


def _prune_snapshots(cfg: Config) -> int:
    """Delete oldest snapshots beyond retention. Returns count deleted."""
    d = snapshot_dir(cfg)
    if not d.is_dir():
        return 0
    ret = _resolve_retention(cfg)
    snaps = sorted(
        (f for f in d.iterdir() if _SNAP_RE.match(f.name)),
        key=lambda f: f.name,
        reverse=True,
    )
    deleted = 0
    for f in snaps[ret:]:
        f.unlink()
        deleted += 1
    if deleted:
        log.info("Pruned %d snapshots (retention=%d)", deleted, ret)
    return deleted


async def _snapshot_loop() -> None:
    cfg: Config = __import__("quart").current_app.config["STATDB"]
    interval = _resolve_interval(cfg)
    log.info("Snapshot scheduler started (interval=%ds, retention=%d)", interval, _resolve_retention(cfg))
    while True:
        try:
            await asyncio.sleep(interval)
            await create_snapshot()
        except asyncio.CancelledError:
            log.info("Snapshot scheduler stopped")
            raise
        except Exception:
            log.exception("Snapshot failed")
            # avoid tight loop on persistent errors
            await asyncio.sleep(60)


def start_snapshot_scheduler(app) -> None:
    """Start the background snapshot task if enabled. Idempotent."""
    global _task
    if _task and not _task.done():
        return
    cfg = app.config["STATDB"]
    if not _is_enabled(cfg):
        return
    _task = asyncio.ensure_future(_snapshot_loop())


def stop_snapshot_scheduler() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None
