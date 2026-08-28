"""F15: custom CSS per view, auto-refresh, kiosk / TV mode."""

from __future__ import annotations

from app.db import Database
from app.views.store import ViewStore


async def test_view_settings_save(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Dashboard")

    resp = await client.post(f"/views/{view['id']}/settings", form={
        "custom_css": ".widget { border: 2px solid red; }",
        "refresh": "30",
        "kiosk": "1",
    })
    assert resp.status_code == 302

    updated = await store.get_view(view["id"])
    assert updated["settings"]["custom_css"] == ".widget { border: 2px solid red; }"
    assert updated["settings"]["refresh"] == 30
    assert updated["settings"]["kiosk"] is True


async def test_view_settings_save_defaults(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Board")

    resp = await client.post(f"/views/{view['id']}/settings", form={
        "custom_css": "",
        "refresh": "0",
    })
    assert resp.status_code == 302

    updated = await store.get_view(view["id"])
    assert updated["settings"]["custom_css"] == ""
    assert updated["settings"]["refresh"] == 0
    assert updated["settings"]["kiosk"] is False


async def test_custom_css_injected_view_detail(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Sales", settings={"custom_css": "h1 { color: hotpink; }"})

    resp = await client.get(f"/views/{view['id']}")
    html = (await resp.get_data()).decode()
    assert resp.status_code == 200
    assert "view-custom-css" in html
    assert "h1 { color: hotpink; }" in html


async def test_custom_css_injected_public_view(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Public Board", settings={"custom_css": ".widget { font-size: 24px; }"})
    view["widgets"] = await store.list_widgets(view["id"])

    resp = await client.get(f"/public/views/{view['id']}")
    html = (await resp.get_data()).decode()
    assert resp.status_code == 200
    assert "view-custom-css" in html
    assert ".widget { font-size: 24px; }" in html


async def test_no_custom_css_no_style_tag(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Plain")

    resp = await client.get(f"/views/{view['id']}")
    html = (await resp.get_data()).decode()
    assert "view-custom-css" not in html


async def test_kiosk_button_present(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Kiosk Test")

    resp = await client.get(f"/views/{view['id']}")
    html = (await resp.get_data()).decode()
    assert resp.status_code == 200
    assert "kiosk-toggle" in html
    assert "data-settings" in html


async def test_public_view_kiosk_via_url(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("TV Board")

    resp = await client.get(f"/public/views/{view['id']}?kiosk=1")
    assert resp.status_code == 200


async def test_public_view_auto_refresh_interval(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Live", settings={"refresh": 15})

    resp = await client.get(f"/public/views/{view['id']}")
    html = (await resp.get_data()).decode()
    assert resp.status_code == 200
    assert '"refresh": 15' in html


async def test_settings_form_has_fields(config, client):
    db = Database(config.db_path)
    store = ViewStore(db)
    view = await store.create_view("Settings Form")

    resp = await client.get(f"/views/{view['id']}")
    html = (await resp.get_data()).decode()
    assert resp.status_code == 200
    assert 'name="custom_css"' in html
    assert 'name="refresh"' in html
    assert 'name="kiosk"' in html
