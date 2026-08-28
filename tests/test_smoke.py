"""F0 smoke tests: app boots, renders, language resolution works."""

from __future__ import annotations

from app import create_app
from app.config import Config


async def test_index_renders_forced_polish(app):
    resp = await app.test_client().get("/")
    assert resp.status_code == 200
    body = await resp.get_data(as_text=True)
    assert "Witaj w StatDB" in body
    assert 'lang="pl"' in body


async def test_index_default_language_is_english(tmp_path):
    app = create_app(
        Config({"STATDB_DATA_DIR": str(tmp_path / "d"), "STATDB_SECRET_KEY": "x"})
    )
    resp = await app.test_client().get("/")
    assert resp.status_code == 200
    body = await resp.get_data(as_text=True)
    assert "Hello from StatDB" in body
    assert 'lang="en"' in body


async def test_language_switch_sets_cookie(app):
    resp = await app.test_client().get("/lang/pl?next=/")
    assert resp.status_code == 302
    cookies = resp.headers.get_all("Set-Cookie") or []
    assert any(c.startswith("statdb_lang=pl") for c in cookies)


async def test_cookie_selects_language_when_not_forced(tmp_path):
    app = create_app(
        Config({"STATDB_DATA_DIR": str(tmp_path / "d"), "STATDB_SECRET_KEY": "x"})
    )
    resp = await app.test_client().get("/", headers={"Cookie": "statdb_lang=pl"})
    assert resp.status_code == 200
    body = await resp.get_data(as_text=True)
    assert "Witaj w StatDB" in body


async def test_env_forces_language_over_cookie(env):
    # `env` fixture forces pl — a cookie asking for en must be ignored.
    cfg = Config(env)
    app = create_app(cfg)
    resp = await app.test_client().get("/", headers={"Cookie": "statdb_lang=en"})
    body = await resp.get_data(as_text=True)
    assert "Witaj w StatDB" in body
