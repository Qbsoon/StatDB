"""F11: auth (password, API token, public links)."""

from __future__ import annotations

import io
import json

from werkzeug.datastructures import FileStorage

from app import create_app
from app.config import Config
from app.db import Database, run_migrations
from app.views.store import ViewStore


def _make_app(env_overrides: dict) -> tuple:
    env = {
        "STATDB_DATA_DIR": "",  # filled by fixture
        "STATDB_SECRET_KEY": "test-secret",
        "STATDB_LANGUAGE": "en",
    }
    env.update(env_overrides)
    return env


async def _client_and_db(config):
    """Helper: fresh app + migrated DB + client."""
    app = create_app(config)
    db = Database(config.db_path)
    await run_migrations(db)
    return app.test_client()


async def test_no_password_open(config):
    """No STATDB_PASSWORD → everything open, no login redirect."""
    client = await _client_and_db(config)
    resp = await client.get("/")
    assert resp.status_code == 200


async def test_password_login_flow(config, tmp_path):
    env = _make_app({"STATDB_PASSWORD": "secret123"})
    env["STATDB_DATA_DIR"] = str(config.data_dir)
    cfg = Config(env)
    app = create_app(cfg)
    db = Database(cfg.db_path)
    await run_migrations(db)
    client = app.test_client()

    # Unauthenticated → redirect to /login
    resp = await client.get("/")
    assert resp.status_code in (301, 302, 303)
    assert "/login" in resp.headers.get("Location", "")

    # Login page accessible
    resp = await client.get("/login")
    assert resp.status_code == 200

    # Wrong password → 401
    resp = await client.post("/login", form={"password": "wrong", "next": "/"})
    assert resp.status_code == 401

    # Correct password → redirect
    resp = await client.post("/login", form={"password": "secret123", "next": "/"})
    assert resp.status_code in (301, 302, 303)

    # Now authenticated
    resp = await client.get("/")
    assert resp.status_code == 200


async def test_api_token_required(config):
    env = _make_app({"STATDB_API_TOKEN": "tok123"})
    env["STATDB_DATA_DIR"] = str(config.data_dir)
    cfg = Config(env)
    app = create_app(cfg)
    db = Database(cfg.db_path)
    await run_migrations(db)
    client = app.test_client()

    # No token → 401
    resp = await client.get("/api/datasets")
    assert resp.status_code == 401

    # Wrong token → 401
    resp = await client.get("/api/datasets", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401

    # Correct token → 200
    resp = await client.get("/api/datasets", headers={"Authorization": "Bearer tok123"})
    assert resp.status_code == 200


async def test_api_token_with_password(config):
    env = _make_app({"STATDB_PASSWORD": "pw", "STATDB_API_TOKEN": "tok"})
    env["STATDB_DATA_DIR"] = str(config.data_dir)
    cfg = Config(env)
    app = create_app(cfg)
    db = Database(cfg.db_path)
    await run_migrations(db)
    client = app.test_client()

    # No auth → 401
    resp = await client.get("/api/datasets")
    assert resp.status_code == 401

    # Token works
    resp = await client.get("/api/datasets", headers={"Authorization": "Bearer tok"})
    assert resp.status_code == 200

    # Session also works after login
    await client.post("/login", form={"password": "pw", "next": "/"})
    resp = await client.get("/api/datasets")
    assert resp.status_code == 200


async def test_public_view_bypasses_auth(config):
    env = _make_app({"STATDB_PASSWORD": "secret"})
    env["STATDB_DATA_DIR"] = str(config.data_dir)
    cfg = Config(env)
    app = create_app(cfg)
    db = Database(cfg.db_path)
    await run_migrations(db)

    # Create a view
    vstore = ViewStore(db)
    view = await vstore.create_view("PublicV")

    client = app.test_client()
    # Public view accessible without login
    resp = await client.get(f"/public/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "PublicV" in html


async def test_logout(config):
    env = _make_app({"STATDB_PASSWORD": "secret123"})
    env["STATDB_DATA_DIR"] = str(config.data_dir)
    cfg = Config(env)
    app = create_app(cfg)
    db = Database(cfg.db_path)
    await run_migrations(db)
    client = app.test_client()

    # Login
    await client.post("/login", form={"password": "secret123", "next": "/"})
    resp = await client.get("/")
    assert resp.status_code == 200

    # Logout
    resp = await client.post("/logout")
    assert resp.status_code in (301, 302, 303)

    # Now redirected again
    resp = await client.get("/")
    assert resp.status_code in (301, 302, 303)


async def test_healthz_no_auth_required(config):
    """Healthz must work without auth even when password/token set."""
    env = _make_app({"STATDB_PASSWORD": "secret", "STATDB_API_TOKEN": "tok"})
    env["STATDB_DATA_DIR"] = str(config.data_dir)
    cfg = Config(env)
    app = create_app(cfg)
    db = Database(cfg.db_path)
    await run_migrations(db)
    client = app.test_client()

    resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["status"] == "ok"
