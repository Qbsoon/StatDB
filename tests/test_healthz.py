"""F1: /healthz endpoint tests."""

from __future__ import annotations


async def test_healthz_ok(app):
    async with app.test_app():  # ensure before_serving migrations ran
        resp = await app.test_client().get("/api/healthz")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data == {"status": "ok", "db": "ok"}


async def test_healthz_db_failure(app, monkeypatch):
    from app.db import Database

    async def boom(self):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(Database, "quick_check", boom)
    async with app.test_app():
        resp = await app.test_client().get("/api/healthz")
    assert resp.status_code == 503
    data = await resp.get_json()
    assert data["status"] == "error"
    assert "disk exploded" in data["db"]


async def test_db_file_created_by_serving(app, config):
    async with app.test_app():
        pass
    assert config.db_path.exists()
