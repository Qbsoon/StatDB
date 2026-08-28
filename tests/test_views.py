"""F5: views & widgets persistence + REST API."""

from __future__ import annotations

import pytest

from app.db import Database, run_migrations
from app.views.store import ViewStore


@pytest.fixture
async def views_db(tmp_path):
    db = Database(tmp_path / "views.db")
    await run_migrations(db)
    return db


# ---------- store: views ----------


async def test_view_crud(views_db):
    store = ViewStore(views_db)
    view = await store.create_view("Przegląd", icon="chart", theme="dark", settings={"refresh": 60})
    assert view["id"] and view["name"] == "Przegląd"
    assert view["settings"] == {"refresh": 60}

    view2 = await store.create_view("Finanse", position=5)
    names = [v["name"] for v in await store.list_views()]
    assert names == ["Przegląd", "Finanse"]

    updated = await store.update_view(view["id"], name="Cockpit", settings={"refresh": 10, "css": "x"})
    assert updated["name"] == "Cockpit"
    assert updated["settings"] == {"refresh": 10, "css": "x"}
    assert updated["theme"] == "dark"  # untouched fields preserved

    with pytest.raises(ValueError):
        await store.create_view("   ")

    await store.delete_view(view2["id"])
    assert [v["id"] for v in await store.list_views()] == [view["id"]]
    with pytest.raises(KeyError):
        await store.delete_view(view2["id"])


async def test_missing_view(views_db):
    store = ViewStore(views_db)
    assert await store.get_view(999) is None
    with pytest.raises(KeyError):
        await store.update_view(999, name="x")


# ---------- store: widgets ----------


async def test_widget_lifecycle(views_db):
    store = ViewStore(views_db)
    view = await store.create_view("Board")

    w1 = await store.add_widget(view["id"], "bar", title="Sum", config={"dataset": "earnings"})
    w2 = await store.add_widget(view["id"], "kpi_sum", title="KPI sum")
    w3 = await store.add_widget(view["id"], "stacked_bar", geometry={"x": 6, "y": 0, "w": 6, "h": 5})

    assert w1["position"] == 0 and w2["position"] == 1  # auto-append
    assert (w3["x"], w3["y"], w3["w"], w3["h"]) == (6, 0, 6, 5)
    assert w1["config"] == {"dataset": "earnings"}

    widgets = await store.list_widgets(view["id"])
    assert [w["type"] for w in widgets] == ["bar", "kpi_sum", "stacked_bar"]

    updated = await store.update_widget(w1["id"], title="Nowy", config={"measure": "avg"})
    assert updated["title"] == "Nowy" and updated["config"] == {"measure": "avg"}
    with pytest.raises(ValueError):
        await store.add_widget(view["id"], "bogus_type")
    with pytest.raises(ValueError):  # x+w > 12
        await store.add_widget(view["id"], "bar", geometry={"x": 8, "w": 6})

    await store.delete_widget(w2["id"])
    assert [w["id"] for w in await store.list_widgets(view["id"])] == [w1["id"], w3["id"]]
    with pytest.raises(KeyError):
        await store.delete_widget(w2["id"])


async def test_layout_bulk_save(views_db):
    store = ViewStore(views_db)
    view = await store.create_view("Board")
    w1 = await store.add_widget(view["id"], "bar")
    w2 = await store.add_widget(view["id"], "note")

    widgets = await store.set_layout(view["id"], [
        {"id": w1["id"], "x": 4, "y": 2, "w": 8, "h": 3, "position": 1},
        {"id": w2["id"], "x": 0, "y": 0, "w": 4, "h": 2, "position": 0},
    ])
    assert [w["id"] for w in widgets] == [w2["id"], w1["id"]]  # re-ordered by position
    assert (widgets[1]["x"], widgets[1]["w"]) == (4, 8)

    with pytest.raises(KeyError):
        await store.set_layout(view["id"], [{"id": 999, "x": 0, "y": 0, "w": 4, "h": 2}])
    with pytest.raises(ValueError):
        await store.set_layout(view["id"], [{"id": w1["id"], "x": 10, "y": 0, "w": 4, "h": 2}])


async def test_widget_validation(views_db):
    store = ViewStore(views_db)
    view = await store.create_view("Board")
    with pytest.raises(ValueError):
        await store.add_widget(view["id"], "unknown_type")
    with pytest.raises(ValueError):
        await store.add_widget(view["id"], "bar", geometry={"x": -1})
    with pytest.raises(KeyError):
        await store.update_widget(999, title="x")


async def test_delete_view_cascades(views_db):
    store = ViewStore(views_db)
    view = await store.create_view("Board")
    w = await store.add_widget(view["id"], "note", title="notatka")
    await store.delete_view(view["id"])
    assert await store.get_widget(w["id"]) is None


# ---------- api ----------


async def test_api_view_crud(config, client):
    resp = await client.get("/api/views")
    assert resp.status_code == 200 and (await resp.get_json()) == []

    resp = await client.post("/api/views", json={"name": "Cockpit", "settings": {"refresh": 30}})
    assert resp.status_code == 201
    view = await resp.get_json()
    assert view["name"] == "Cockpit" and view["settings"] == {"refresh": 30}

    resp = await client.get("/api/views")
    names = [v["name"] for v in (await resp.get_json())]
    assert names == ["Cockpit"]

    resp = await client.patch(f"/api/views/{view['id']}", json={"name": "Cockpit 2", "theme": "dark"})
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["name"] == "Cockpit 2" and data["theme"] == "dark"
    assert data["settings"] == {"refresh": 30}

    resp = await client.post("/api/views", json={"name": "  "})
    assert resp.status_code == 400
    resp = await client.patch("/api/views/999", json={"name": "x"})
    assert resp.status_code == 404


async def test_api_widgets(config, client):
    resp = await client.post("/api/views", json={"name": "Board"})
    view = await resp.get_json()

    resp = await client.post(f"/api/views/{view['id']}/widgets", json={
        "type": "bar", "title": "Sum", "config": {"dataset": "earnings", "measure": "sum"},
        "x": 0, "y": 0, "w": 6, "h": 4,
    })
    assert resp.status_code == 201
    widget = await resp.get_json()
    assert widget["type"] == "bar" and widget["config"]["measure"] == "sum"
    assert (widget["x"], widget["y"], widget["w"], widget["h"]) == (0, 0, 6, 4)

    resp = await client.post(f"/api/views/{view['id']}/widgets", json={"type": "bogus"})
    assert resp.status_code == 400
    resp = await client.post("/api/views/999/widgets", json={"type": "bar"})
    assert resp.status_code == 404
    resp = await client.post(f"/api/views/{view['id']}/widgets", json={"type": "bar", "x": 9, "w": 6})
    assert resp.status_code == 400  # x+w > 12

    resp = await client.get(f"/api/views/{view['id']}")
    data = await resp.get_json()
    assert [w["type"] for w in data["widgets"]] == ["bar"]

    resp = await client.patch(f"/api/widgets/{widget['id']}", json={"title": "Nowy tytuł", "w": 4})
    assert resp.status_code == 200 and (await resp.get_json())["w"] == 4
    resp = await client.patch(f"/api/widgets/{widget['id']}", json={"w": 13})
    assert resp.status_code == 400

    resp = await client.delete(f"/api/widgets/{widget['id']}")
    assert resp.status_code == 200
    resp = await client.get(f"/api/views/{view['id']}")
    assert (await resp.get_json())["widgets"] == []


async def test_api_layout(config, client):
    resp = await client.post("/api/views", json={"name": "Board"})
    view = await resp.get_json()
    ids = []
    for t in ("bar", "note"):
        resp = await client.post(f"/api/views/{view['id']}/widgets", json={"type": t})
        ids.append((await resp.get_json())["id"])

    resp = await client.put(f"/api/views/{view['id']}/layout", json=[
        {"id": ids[0], "x": 4, "y": 1, "w": 8, "h": 3, "position": 1},
        {"id": ids[1], "x": 0, "y": 0, "w": 4, "h": 2, "position": 0},
    ])
    assert resp.status_code == 200
    widgets = await resp.get_json()
    assert [w["id"] for w in widgets] == [ids[1], ids[0]]
    assert widgets[0]["w"] == 4 and widgets[1]["x"] == 4

    resp = await client.put(f"/api/views/{view['id']}/layout", json=[{"id": 999, "x": 0, "y": 0, "w": 2, "h": 2}])
    assert resp.status_code == 404
    resp = await client.put(f"/api/views/{view['id']}/layout", json="not-a-list")
    assert resp.status_code == 400