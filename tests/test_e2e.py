"""F14: end-to-end key flows via HTTP API + web.

Flow: create dataset → add columns → add rows → aggregate →
       create view → add widgets → verify dashboard renders.
"""

from __future__ import annotations

from app.catalog.store import CatalogStore
from app.db import Database
from app.rows.store import RowStore
from app.views.store import ViewStore


# ── E2E flow 1: dataset → rows → aggregate ───────────────

async def test_e2e_dataset_rows_aggregate(client, config):
    """Create a dataset, add columns, insert rows, run aggregation."""
    # 1. Create dataset via API
    resp = await client.post("/api/datasets", json={"name": "Earnings", "slug": "earnings"})
    assert resp.status_code == 201
    ds = await resp.get_json()
    ds_id = ds["id"]

    # 2. Add columns
    for key, label, typ, cfg, pos in [
        ("month", "Month", "year-month", {"input_format": "MM-YYYY"}, 1),
        ("source", "Source", "select", {
            "options": [
                {"key": "uop", "label": {"en": "Contract", "pl": "Umowa"}, "color": "#3b82f6"},
                {"key": "b2b", "label": {"en": "B2B", "pl": "Faktura"}, "color": "#f59e0b"},
            ]
        }, 2),
        ("amount", "Amount", "currency", {"currency_code": "PLN"}, 3),
    ]:
        resp = await client.post(
            f"/api/datasets/{ds_id}/columns",
            json={"key": key, "label": label, "type": typ, "config": cfg, "position": pos},
        )
        assert resp.status_code == 201

    # 3. Add rows via API
    rows = [
        {"month": "01-2026", "source": "uop", "amount": 9000},
        {"month": "02-2026", "source": "uop", "amount": 9000},
        {"month": "03-2026", "source": "uop", "amount": 6000},
        {"month": "03-2026", "source": "b2b", "amount": 8000},
        {"month": "04-2026", "source": "b2b", "amount": 12000},
        {"month": "05-2026", "source": "b2b", "amount": 4000},
    ]
    for row in rows:
        resp = await client.post(f"/api/datasets/{ds_id}/rows", json=row)
        assert resp.status_code == 201

    # 4. List rows
    resp = await client.get(f"/api/datasets/{ds_id}/rows")
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["total"] == 6

    # 5. Aggregate: sum
    resp = await client.post("/api/aggregate", json={
        "dataset": ds_id,
        "measure": "sum",
        "column": "amount",
    })
    assert resp.status_code == 200
    agg = await resp.get_json()
    assert agg["kind"] == "scalar"
    assert agg["value"] == 48000.0

    # 6. Aggregate: group-by source
    resp = await client.post("/api/aggregate", json={
        "dataset": ds_id,
        "measure": "sum",
        "column": "amount",
        "group_by": "source",
    })
    assert resp.status_code == 200
    agg = await resp.get_json()
    assert agg["kind"] == "grouped"
    labels = {item["label"] for item in agg["items"]}
    assert "Contract" in labels
    assert "B2B" in labels


# ── E2E flow 2: dataset → view → widgets → dashboard ────

async def test_e2e_view_dashboard(client, config):
    """Create dataset, rows, view with 3 widgets, verify dashboard page."""
    # Seed data via stores (faster than API for setup)
    db = Database(config.db_path)
    cstore = CatalogStore(db)
    rstore = RowStore(db)

    ds = await cstore.create_dataset("sales", "Sales")
    await cstore.add_column(ds["id"], "month", "Month", "year-month", {"input_format": "MM-YYYY"}, 1)
    await cstore.add_column(ds["id"], "region", "Region", "select", {
        "options": [
            {"key": "eu", "label": {"en": "Europe", "pl": "Europa"}, "color": "#3b82f6"},
            {"key": "us", "label": {"en": "USA", "pl": "USA"}, "color": "#f59e0b"},
        ]
    }, 2)
    await cstore.add_column(ds["id"], "revenue", "Revenue", "currency", {"currency_code": "EUR"}, 3)

    ds = await cstore.get_dataset(dataset_id=ds["id"])
    for month, region, rev in [
        ("01-2026", "eu", 5000), ("01-2026", "us", 3000),
        ("02-2026", "eu", 7000), ("02-2026", "us", 2000),
        ("03-2026", "eu", 6000), ("03-2026", "us", 8000),
    ]:
        await rstore.create_row(ds, {"month": month, "region": region, "revenue": rev})

    # Create view via API
    resp = await client.post("/api/views", json={"name": "Sales Dashboard"})
    assert resp.status_code == 201
    view = await resp.get_json()
    view_id = view["id"]

    # Add 3 widgets: KPI sum, bar chart, stacked bar
    for wtype, title, cfg in [
        ("kpi_sum", "Total Revenue", {"dataset_id": ds["id"], "column": "revenue"}),
        ("bar", "Revenue by Region", {"dataset_id": ds["id"], "column": "revenue", "group_by": "region"}),
        ("stacked_bar", "Revenue by Month/Region", {
            "dataset_id": ds["id"], "column": "revenue",
            "group_by": "month", "series": "region",
        }),
    ]:
        resp = await client.post(f"/api/views/{view_id}/widgets", json={
            "type": wtype, "title": title, "config": cfg,
        })
        assert resp.status_code == 201

    # Get view with widgets
    resp = await client.get(f"/api/views/{view_id}")
    assert resp.status_code == 200
    view_full = await resp.get_json()
    assert len(view_full["widgets"]) == 3
    assert view_full["widgets"][0]["type"] == "kpi_sum"
    assert view_full["widgets"][1]["type"] == "bar"
    assert view_full["widgets"][2]["type"] == "stacked_bar"

    # Dashboard page renders
    resp = await client.get(f"/views/{view_id}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Sales Dashboard" in html
    assert "Total Revenue" in html
    assert "Revenue by Region" in html

    # Set layout
    resp = await client.put(f"/api/views/{view_id}/layout", json={
        "layout": [
            {"id": view_full["widgets"][0]["id"], "x": 0, "y": 0, "w": 12, "h": 3},
            {"id": view_full["widgets"][1]["id"], "x": 0, "y": 3, "w": 6, "h": 6},
            {"id": view_full["widgets"][2]["id"], "x": 6, "y": 3, "w": 6, "h": 6},
        ]
    })
    assert resp.status_code == 200

    # Verify layout persisted
    resp = await client.get(f"/api/views/{view_id}")
    view_full = await resp.get_json()
    w0 = view_full["widgets"][0]
    assert (w0["x"], w0["y"], w0["w"], w0["h"]) == (0, 0, 12, 3)


# ── E2E flow 3: CSV import → export ───────────────────────

async def test_e2e_csv_import_export(client, config):
    """Import CSV, verify rows, export CSV back."""
    csv_content = "month,source,amount\n01-2026,uop,9000\n02-2026,uop,9500\n03-2026,b2b,8000\n"
    import io
    from werkzeug.datastructures import FileStorage

    resp = await client.post("/api/datasets/import-csv", files={
        "file": FileStorage(stream=io.BytesIO(csv_content.encode()), filename="test.csv"),
    }, form={
        "name": "Import Test",
        "slug": "import_test",
    })
    assert resp.status_code in (200, 201)
    data = await resp.get_json()
    ds_id = data["dataset_id"]
    assert ds_id

    # Verify rows
    resp = await client.get(f"/api/datasets/{ds_id}/rows")
    assert resp.status_code == 200
    rows = await resp.get_json()
    assert rows["total"] == 3

    # Export CSV
    resp = await client.get(f"/api/datasets/{ds_id}/export?format=csv")
    assert resp.status_code == 200
    csv_out = (await resp.get_data()).decode()
    assert "month" in csv_out
    assert "01-2026" in csv_out


# ── E2E flow 4: public view ──────────────────────────────

async def test_e2e_public_view(client, config):
    """Create view, access via /public/views/<id> (no auth)."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Public Report")

    resp = await client.get(f"/public/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Public Report" in html


# ── E2E flow 5: backup + restore views ────────────────────

async def test_e2e_backup_and_views_transfer(client, config):
    """Backup DB, export views, import views into fresh state."""
    # Seed a view
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Backup Test", settings={"refresh": 30})

    # Export views
    resp = await client.get("/api/views/export")
    assert resp.status_code == 200
    export_data = await resp.get_json()
    assert export_data["version"] == 1
    assert len(export_data["views"]) >= 1

    # Backup
    resp = await client.get("/api/backup")
    assert resp.status_code == 200

    # Import views back (idempotent round-trip)
    resp = await client.post("/api/views/import", json=export_data)
    assert resp.status_code in (200, 201)
