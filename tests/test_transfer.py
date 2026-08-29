"""F10: import CSV/JSON, export CSV/JSON, backup, views export/import, snapshots."""

from __future__ import annotations

import io
import json

from werkzeug.datastructures import FileStorage

from app.catalog.store import CatalogStore
from app.db import Database
from app.rows.store import RowStore
from app.views.store import ViewStore


_CSV = "Name,Age,City\nAlice,30,Berlin\nBob,25,Munich\nCharlie,35,Hamburg\n"


async def test_csv_import_web(config, client):
    resp = await client.post(
        "/datasets/import",
        files={"file": FileStorage(
            stream=io.BytesIO(_CSV.encode()), filename="people.csv",
            content_type="text/csv",
        )},
    )
    assert resp.status_code in (301, 302)
    # dataset created
    store = CatalogStore(Database(config.db_path))
    ds = await store.get_dataset(slug="people")
    assert ds is not None
    assert ds["name"] == "People"
    cols = {c["key"]: c for c in ds["columns"]}
    assert "name" in cols and cols["name"]["type"] == "text"
    assert "age" in cols and cols["age"]["type"] == "integer"
    assert "city" in cols
    # rows imported
    rs = RowStore(Database(config.db_path))
    result = await rs.list_rows(ds, page=1, page_size=50)
    assert len(result["items"]) == 3


async def test_json_import_new_dataset_web(config, client):
    """JSON import creates a new dataset with full schema from the JSON."""
    payload = {
        "dataset": {
            "slug": "imported",
            "name": "Imported Dataset",
            "description": "from JSON",
            "columns": [
                {"key": "name", "label": "Name", "type": "text", "config": {}},
                {"key": "amount", "label": "Amount", "type": "float", "config": {}},
            ],
        },
        "rows": [
            {"name": "Alpha", "amount": 10.5},
            {"name": "Beta", "amount": 20.0},
        ],
    }
    content = json.dumps(payload).encode()
    resp = await client.post(
        "/datasets/import",
        files={"file": FileStorage(
            stream=io.BytesIO(content), filename="imported.json",
            content_type="application/json",
        )},
    )
    assert resp.status_code in (301, 302)
    store = CatalogStore(Database(config.db_path))
    ds = await store.get_dataset(slug="imported")
    assert ds is not None
    assert ds["name"] == "Imported Dataset"
    cols = {c["key"]: c for c in ds["columns"]}
    assert "name" in cols and cols["name"]["type"] == "text"
    assert "amount" in cols and cols["amount"]["type"] == "float"
    rs = RowStore(Database(config.db_path))
    result = await rs.list_rows(ds, page=1, page_size=50)
    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "Alpha"


async def test_csv_import_into_existing_web(config, client):
    """CSV import appends rows to an existing dataset, matching by column key/label."""
    store = CatalogStore(Database(config.db_path))
    ds = await store.create_dataset("existing", "Existing")
    await store.add_column(ds["id"], "name", "Name", "text", {}, 1)
    await store.add_column(ds["id"], "age", "Age", "integer", {}, 2)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(Database(config.db_path))
    await rs.create_row(ds, {"name": "Original", "age": 99})

    csv_data = "Name,Age\nAlice,30\nBob,25\n"
    resp = await client.post(
        "/datasets/import",
        files={"file": FileStorage(
            stream=io.BytesIO(csv_data.encode()), filename="extra.csv",
            content_type="text/csv",
        )},
        form={"dataset_id": str(ds["id"])},
    )
    assert resp.status_code in (301, 302)
    ds = await store.get_dataset(dataset_id=ds["id"])
    result = await rs.list_rows(ds, page=1, page_size=50)
    assert len(result["items"]) == 3  # original + 2 imported
    names = [r["name"] for r in result["items"]]
    assert "Original" in names
    assert "Alice" in names
    assert "Bob" in names


async def test_json_import_into_existing_web(config, client):
    """JSON import appends rows to an existing dataset, matching by column key."""
    store = CatalogStore(Database(config.db_path))
    ds = await store.create_dataset("jexisting", "JSON Existing")
    await store.add_column(ds["id"], "name", "Name", "text", {}, 1)
    await store.add_column(ds["id"], "val", "Val", "integer", {}, 2)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(Database(config.db_path))
    await rs.create_row(ds, {"name": "Orig", "val": 1})

    payload = {
        "dataset": {
            "slug": "jexisting", "name": "JSON Existing",
            "columns": [
                {"key": "name", "label": "Name", "type": "text", "config": {}},
                {"key": "val", "label": "Val", "type": "integer", "config": {}},
            ],
        },
        "rows": [
            {"name": "X", "val": 10},
            {"name": "Y", "val": 20},
        ],
    }
    content = json.dumps(payload).encode()
    resp = await client.post(
        "/datasets/import",
        files={"file": FileStorage(
            stream=io.BytesIO(content), filename="jexisting.json",
            content_type="application/json",
        )},
        form={"dataset_id": str(ds["id"])},
    )
    assert resp.status_code in (301, 302)
    ds = await store.get_dataset(dataset_id=ds["id"])
    result = await rs.list_rows(ds, page=1, page_size=50)
    assert len(result["items"]) == 3  # original + 2 imported


async def test_csv_import_api(config, client):
    """API CSV import returns JSON result."""
    resp = await client.post(
        "/api/datasets/import-csv",
        files={"file": FileStorage(
            stream=io.BytesIO(_CSV.encode()), filename="api_people.csv",
            content_type="text/csv",
        )},
    )
    assert resp.status_code == 201
    data = await resp.get_json()
    assert data["slug"] == "api_people"
    assert data["imported"] == 3
    assert data["columns"] == 3


async def test_json_import_api(config, client):
    """API JSON import returns JSON result."""
    payload = {
        "dataset": {
            "slug": "api_json",
            "name": "API JSON",
            "columns": [
                {"key": "title", "label": "Title", "type": "text", "config": {}},
            ],
        },
        "rows": [{"title": "Hello"}, {"title": "World"}],
    }
    resp = await client.post("/api/datasets/import-json", json=payload)
    assert resp.status_code == 201
    data = await resp.get_json()
    assert data["slug"] == "api_json"
    assert data["imported"] == 2


async def test_csv_import_api_existing(config, client):
    """API CSV import into existing dataset appends rows."""
    store = CatalogStore(Database(config.db_path))
    ds = await store.create_dataset("apiexist", "API Existing")
    await store.add_column(ds["id"], "name", "Name", "text", {}, 1)
    resp = await client.post(
        "/api/datasets/import-csv",
        files={"file": FileStorage(
            stream=io.BytesIO(b"Name\nAlice\n"), filename="x.csv",
            content_type="text/csv",
        )},
        form={"dataset_id": str(ds["id"])},
    )
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["dataset_id"] == ds["id"]
    assert data["imported"] == 1


async def test_json_import_api_existing(config, client):
    """API JSON import into existing dataset appends rows."""
    store = CatalogStore(Database(config.db_path))
    ds = await store.create_dataset("apijexist", "API JSON Existing")
    await store.add_column(ds["id"], "k", "K", "text", {}, 1)
    payload = {
        "dataset": {"slug": "apijexist", "name": "API JSON Existing",
                      "columns": [{"key": "k", "label": "K", "type": "text", "config": {}}]},
        "rows": [{"k": "v1"}, {"k": "v2"}],
    }
    resp = await client.post(
        "/api/datasets/import-json?dataset_id=" + str(ds["id"]),
        json=payload,
    )
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["imported"] == 2


async def test_csv_export_web(config, client):
    store = CatalogStore(Database(config.db_path))
    ds = await store.create_dataset("exp", "Export")
    await store.add_column(ds["id"], "name", "Name", "text", {}, 1)
    await store.add_column(ds["id"], "val", "Val", "integer", {}, 2)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(Database(config.db_path))
    await rs.create_row(ds, {"name": "Foo", "val": 42})

    resp = await client.get(f"/datasets/{ds['id']}/export?format=csv")
    assert resp.status_code == 200
    text = (await resp.get_data()).decode()
    assert "Name" in text and "Val" in text and "Foo" in text and "42" in text


async def test_json_export_web(config, client):
    store = CatalogStore(Database(config.db_path))
    ds = await store.create_dataset("jexp", "JSON Export")
    await store.add_column(ds["id"], "name", "Name", "text", {}, 1)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(Database(config.db_path))
    await rs.create_row(ds, {"name": "Bar"})

    resp = await client.get(f"/datasets/{ds['id']}/export?format=json")
    assert resp.status_code == 200
    data = json.loads(await resp.get_data())
    assert data["dataset"]["slug"] == "jexp"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["name"] == "Bar"


async def test_backup_download_web(config, client):
    resp = await client.get("/backup")
    assert resp.status_code == 200
    data = await resp.get_data()
    assert len(data) > 0
    assert b"SQLite format 3" in data


async def test_views_export_api(config, client):
    vstore = ViewStore(Database(config.db_path))
    view = await vstore.create_view("ExpView")
    await vstore.add_widget(view["id"], "note", title="N1")

    resp = await client.get("/api/views/export")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["version"] == 1
    assert len(data["views"]) == 1
    assert data["views"][0]["name"] == "ExpView"
    assert len(data["views"][0]["widgets"]) == 1


async def test_views_import_api(config, client):
    payload = {
        "version": 1,
        "views": [
            {
                "name": "Imported",
                "icon": "",
                "theme": "",
                "settings": {},
                "position": 0,
                "widgets": [
                    {"type": "note", "title": "W1", "config": {"text": "hi"},
                     "x": 0, "y": 0, "w": 6, "h": 4, "position": 0},
                ],
            },
        ],
    }
    resp = await client.post("/api/views/import", json=payload)
    assert resp.status_code == 201
    data = await resp.get_json()
    assert data["imported_views"] == 1
    assert data["imported_widgets"] == 1

    vstore = ViewStore(Database(config.db_path))
    views = await vstore.list_views()
    assert any(v["name"] == "Imported" for v in views)


async def test_views_import_web(config, client):
    payload = {
        "version": 1,
        "views": [{"name": "WebImport", "widgets": [
            {"type": "note", "title": "X", "config": {}, "x": 0, "y": 0, "w": 6, "h": 4, "position": 0},
        ]}],
    }
    content = json.dumps(payload).encode()
    resp = await client.post(
        "/transfer/views-import",
        files={"file": FileStorage(
            stream=io.BytesIO(content), filename="views.json",
            content_type="application/json",
        )},
    )
    assert resp.status_code in (301, 302)
    vstore = ViewStore(Database(config.db_path))
    views = await vstore.list_views()
    assert any(v["name"] == "WebImport" for v in views)


async def test_transfer_page(config, client):
    resp = await client.get("/transfer")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Import" in html or "Importuj" in html


async def test_snapshot_create_list_delete(config, client):
    # trigger via API
    resp = await client.post("/api/snapshots/trigger")
    assert resp.status_code == 201
    data = await resp.get_json()
    assert data["name"].startswith("statdb-snapshot-")

    # list
    resp = await client.get("/api/snapshots")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert any(s["name"].startswith("statdb-snapshot-") for s in data["snapshots"])

    # delete
    snap_name = data["snapshots"][0]["name"]
    resp = await client.delete(f"/api/snapshots/{snap_name}")
    assert resp.status_code == 200


async def test_snapshot_trigger_web(config, client):
    resp = await client.post("/transfer/snapshots/trigger")
    assert resp.status_code in (301, 302)
    from app.snapshots import list_snapshot_files
    assert len(list_snapshot_files(config)) >= 1
