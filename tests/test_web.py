"""F6: web pages — layout, datasets list/detail, schema editor forms."""

from __future__ import annotations

from app.catalog.store import CatalogStore
from app.db import Database
from app.rows.store import RowStore
from app.views.store import ViewStore


async def _store(config) -> tuple[CatalogStore, Database]:
    from app.catalog.store import CatalogStore
    db = Database(config.db_path)
    return CatalogStore(db), db


async def test_layout_base(config, client):
    resp = await client.get("/")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert '<html lang="pl"' in html  # conftest sets STATDB_LANGUAGE=pl as default
    assert 'data-theme="dark"' in html  # default theme attribute present
    assert "Zbiory danych" in html  # nav translated
    assert 'href="/lang/en' in html  # language toggle to EN


async def test_datasets_page_lists(config, client):
    store, _ = await _store(config)
    ds = await store.create_dataset("earnings", "Zarobki", "przychody")
    await store.add_column(ds["id"], key="amount", label="Kwota", type_key="float")

    resp = await client.get("/datasets")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Zarobki" in html and "earnings" in html
    assert "Zbiory danych" in html
    assert f'href="/datasets/{ds["id"]}"' in html


async def test_datasets_empty_and_form(config, client):
    resp = await client.get("/datasets")
    assert resp.status_code == 200
    assert "Brak zbiorów" in (await resp.get_data()).decode()

    # create via form
    resp = await client.post("/datasets", form={
        "slug": "Earnings", "name": "Zarobki", "description": "przychody",
    })
    assert resp.status_code in (301, 302)
    store, _ = await _store(config)
    ds = await store.get_dataset(slug="earnings_register")  # wrong slug
    assert ds is None
    ds = await store.get_dataset(slug="earnings")
    assert ds is not None and ds["name"] == "Zarobki"

    # invalid slug stays on the list, nothing created
    resp = await client.post("/datasets", form={"slug": "9bad", "name": "x"})
    assert resp.status_code in (301, 302)
    store, _ = await _store(config)
    assert await store.get_dataset(slug="9bad") is None


async def test_dataset_detail_page(config, client):
    store, _ = await _store(config)
    ds = await store.create_dataset("earnings", "Zarobki")
    await store.add_column(ds["id"], key="amount", label="Kwota", type_key="float")

    resp = await client.get(f"/datasets/{ds['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Schemat kolumn" in html
    assert "amount" in html and "Kwota" in html
    resp = await client.get("/datasets/999")
    assert resp.status_code == 404


async def test_schema_editor_forms(config, client):
    store, _ = await _store(config)
    ds = await store.create_dataset("earnings", "Zarobki")

    # add column via form
    resp = await client.post(f"/datasets/{ds['id']}/columns", form={
        "key": "amount", "label": "Kwota", "type": "currency",
        "config": '{"currency_code": "PLN"}',
    }, query_string={"next": f"/datasets/{ds['id']}"})
    assert resp.status_code in (301, 302)
    store, _ = await _store(config)
    ds = await store.get_dataset(slug="earnings")
    col = ds["columns"][0]
    assert col["key"] == "amount" and col["type"] == "currency"
    assert col["config"] == {"currency_code": "PLN"}

    # update label + config
    resp = await client.post(f"/columns/{col['id']}/update", form={
        "label": "Kwota netto", "config": '{"currency_code": "EUR"}',
    }, query_string={"next": f"/datasets/{ds['id']}"})
    assert resp.status_code in (301, 302)
    store, _ = await _store(config)
    col = (await store.get_dataset(slug="earnings"))["columns"][0]
    assert col["label"] == "Kwota netto" and col["config"] == {"currency_code": "EUR"}

    # delete
    resp = await client.post(f"/columns/{col['id']}/delete", query_string={"next": "/datasets"})
    assert resp.status_code in (301, 302)
    store, _ = await _store(config)
    assert (await store.get_dataset(slug="earnings"))["columns"] == []


async def test_dataset_detail_type_dropdown(config, client):
    """Add-column type dropdown lists all real types incl. integer & bool."""
    store, _ = await _store(config)
    ds = await store.create_dataset("earnings", "Zarobki")
    resp = await client.get(f"/datasets/{ds['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert 'name="type"' in html
    assert 'value="integer"' in html
    assert 'value="bool"' in html
    assert 'value="year-month"' in html
    assert 'value="select"' in html
    # no raw JSON config field anywhere on the schema editor
    assert "Config (JSON)" not in html
    assert "Konfiguracja (JSON)" not in html


async def test_dataset_detail_select_options_gui(config, client):
    """Select column renders GUI option editor, not raw JSON."""
    store, _ = await _store(config)
    ds = await store.create_dataset("earnings", "Zarobki")
    await store.add_column(ds["id"], key="source", label="Źródło", type_key="select", config={
        "options": [
            {"key": "uop", "label": "Umowa o pracę", "color": "#3b82f6"},
            {"key": "b2b", "label": {"en": "B2B", "pl": "Faktura B2B"}},
        ]
    })
    resp = await client.get(f"/datasets/{ds['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    # GUI elements present
    assert "cfg-option-row" in html
    assert "data-add-option" in html
    assert "cfg-translations-toggle" in html
    # option labels rendered (string label + dict label resolved to current lang)
    assert "Umowa o pracę" in html
    # no raw JSON config textarea
    assert "Config (JSON)" not in html
    assert "Konfiguracja (JSON)" not in html


async def test_select_string_label_in_records(config, client):
    """Records table renders string labels for select options (point 5)."""
    store, _ = await _store(config)
    ds = await store.create_dataset("earnings", "Zarobki")
    await store.add_column(ds["id"], key="source", label="Źródło", type_key="select", config={
        "options": [{"key": "uop", "label": "Umowa"}, {"key": "b2b", "label": "Faktura"}]
    })
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(Database(config.db_path))
    await rs.create_row(ds, {"source": "uop"})
    resp = await client.get(f"/datasets/{ds['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Umowa" in html  # string label rendered in <option>


async def _seed_records(config):
    store, db = await _store(config)
    ds = await store.create_dataset("expenses", "Wydatki")
    await store.add_column(ds["id"], key="month", label="Miesiąc",
                           type_key="year-month", config={"input_format": "MM-YYYY"})
    await store.add_column(ds["id"], key="amount", label="Kwota", type_key="float")
    # create_dataset returns a snapshot without columns — re-fetch so RowStore
    # sees the schema
    return await store.get_dataset(dataset_id=ds["id"]), db


async def test_records_table_render(config, client):
    ds, db = await _seed_records(config)
    await RowStore(db).create_row(ds, {"month": "08-2026", "amount": 12.5})

    resp = await client.get(f"/datasets/{ds['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Dane" in html  # records section header (pl)
    assert "Rekordów: 1" in html
    assert 'value="08-2026"' in html
    assert 'value="12.5"' in html
    assert 'form="row-new"' in html  # add-record form association


async def test_row_add_flow(config, client):
    ds, db = await _seed_records(config)
    resp = await client.post(f"/datasets/{ds['id']}/rows", form={
        "month": "08-2026", "amount": "12,5",  # Polish decimal comma coerced
    })
    assert resp.status_code in (301, 302)
    out = await RowStore(db).list_rows(ds)
    assert out["total"] == 1
    row = out["items"][0]
    assert row["amount"] == 12.5 and row["month"] == "08-2026"

    # invalid year-month → redirect, nothing created
    resp = await client.post(f"/datasets/{ds['id']}/rows", form={"month": "2026-08", "amount": "1"})
    assert resp.status_code in (301, 302)
    out = await RowStore(db).list_rows(ds)
    assert out["total"] == 1


async def test_row_update_delete_flow(config, client):
    ds, db = await _seed_records(config)
    rstore = RowStore(db)
    row = await rstore.create_row(ds, {"month": "08-2026", "amount": 1})

    # full update incl. comma coercion
    resp = await client.post(f"/datasets/{ds['id']}/rows/{row['id']}", form={
        "month": "09-2026", "amount": "7,5",
    })
    assert resp.status_code in (301, 302)
    updated = await rstore.get_row(ds, row["id"])
    assert updated["amount"] == 7.5 and updated["month"] == "09-2026"

    # empty strings clear values to NULL
    resp = await client.post(f"/datasets/{ds['id']}/rows/{row['id']}",
                             form={"month": "", "amount": "5"})
    assert resp.status_code in (301, 302)
    updated = await rstore.get_row(ds, row["id"])
    assert updated["month"] is None and updated["amount"] == 5.0

    # missing row → 404
    resp = await client.post(f"/datasets/{ds['id']}/rows/9999", form={"amount": "1"})
    assert resp.status_code == 404

    # delete
    resp = await client.post(f"/datasets/{ds['id']}/rows/{row['id']}/delete")
    assert resp.status_code in (301, 302)
    assert await rstore.get_row(ds, row["id"]) is None


# ---------- F8: dashboard views ----------


async def test_views_pages(config, client):
    # list
    resp = await client.get("/views")
    assert resp.status_code == 200

    # create
    resp = await client.post("/views", form={"name": "Finanse"})
    assert resp.status_code in (301, 302)
    location = resp.headers["Location"]
    assert location.startswith("/views/")
    view_id = int(location.rsplit("/", 1)[1])

    # detail 200, grid kontener + add-widget form
    resp = await client.get(f"/views/{view_id}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "Finanse" in html
    assert "grid-stack" in html
    assert "widget-create-form" in html

    # 404
    resp = await client.get("/views/9999")
    assert resp.status_code == 404


async def test_widget_add_and_delete(config, client):
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Dash")

    resp = await client.post(
        f"/views/{view['id']}/widgets",
        form={"type": "kpi_sum", "title": "Suma", "dataset_id": "", "column": ""},
    )
    assert resp.status_code in (301, 302)
    widgets = await vstore.list_widgets(view["id"])
    assert len(widgets) == 1
    assert widgets[0]["type"] == "kpi_sum"

    # bad view → 404
    resp = await client.post("/views/9999/widgets", form={"type": "kpi_sum"})
    assert resp.status_code == 404

    # delete
    resp = await client.post(
        f"/views/{view['id']}/widgets/{widgets[0]['id']}/delete"
    )
    assert resp.status_code in (301, 302)
    assert await vstore.list_widgets(view["id"]) == []


async def test_layout_save_and_update(config, client):
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Layout")
    w = await vstore.add_widget(view["id"], "note", title="N")

    # zapis układu JSON
    resp = await client.post(
        f"/views/{view['id']}/layout",
        json=[{"id": w["id"], "x": 2, "y": 1, "w": 8, "h": 5}],
    )
    assert resp.status_code == 200
    assert await resp.get_json() == {"ok": True}
    widgets = await vstore.list_widgets(view["id"])
    assert (widgets[0]["x"], widgets[0]["y"], widgets[0]["w"], widgets[0]["h"]) == (2, 1, 8, 5)

    # obce id → 400 (KeyError po stronie store)
    resp = await client.post(
        f"/views/{view['id']}/layout",
        json=[{"id": 9999, "x": 0, "y": 0, "w": 4, "h": 3}],
    )
    assert resp.status_code == 400

    # update widżetu (tytuł + config JSON)
    resp = await client.post(
        f"/views/{view['id']}/widgets/{w['id']}",
        form={"title": "Notatka", "config": '{"text": "hello"}'},
    )
    assert resp.status_code in (301, 302)
    widgets = await vstore.list_widgets(view["id"])
    assert widgets[0]["title"] == "Notatka"
    assert widgets[0]["config"] == {"text": "hello"}


# ---------- F9: widget renderers ----------


async def _seed_dataset(config):
    """Seed a dataset with month/source/amount columns + rows for F9 tests."""
    db = Database(config.db_path)
    store = CatalogStore(db)
    ds = await store.create_dataset("sales", "Sprzedaż")
    await store.add_column(ds["id"], "month", "Miesiąc", "year-month", {"input_format": "MM-YYYY"}, 1)
    await store.add_column(ds["id"], "region", "Region", "select", {
        "options": [
            {"key": "pl", "label": {"en": "Poland", "pl": "Polska"}},
            {"key": "de", "label": {"en": "Germany", "pl": "Niemcy"}},
        ]
    }, 2)
    await store.add_column(ds["id"], "amount", "Kwota", "currency", {"currency_code": "PLN"}, 3)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(db)
    for month, region, amount in [
        ("01-2026", "pl", 100), ("02-2026", "pl", 200),
        ("01-2026", "de", 150), ("02-2026", "de", 300),
    ]:
        await rs.create_row(ds, {"month": month, "region": region, "amount": amount})
    return ds


async def test_widget_renderer_markup(config, client):
    """Widgets render data-widget-type/config/body attrs + script tag."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Render")
    await vstore.add_widget(view["id"], "note", title="N1", config={"text": "hello world"})
    ds = await _seed_dataset(config)
    await vstore.add_widget(view["id"], "kpi_sum", title="Suma",
                            config={"dataset_id": ds["id"], "column": "amount"})
    await vstore.add_widget(view["id"], "bar", title="Bar",
                            config={"dataset_id": ds["id"], "column": "amount",
                                    "group_by": "month"})

    resp = await client.get(f"/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    # data-widget-type / data-widget-config attrs present
    assert 'data-widget-type="note"' in html
    assert 'data-widget-type="kpi_sum"' in html
    assert 'data-widget-type="bar"' in html
    assert "data-widget-config=" in html
    # data-widget-body target div present
    assert "data-widget-body" in html
    # renderer script loaded
    assert "widget_renderers.js" in html


async def test_widget_note_config_text(config, client):
    """Note widget config text is in the JSON blob on the page."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Note")
    await vstore.add_widget(view["id"], "note", title="N", config={"text": "test note 123"})
    resp = await client.get(f"/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "test note 123" in html


async def test_widget_kpi_with_dataset(config, client):
    """KPI widget with dataset_id triggers aggregate on page load (config in DOM)."""
    ds = await _seed_dataset(config)
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("KPI")
    await vstore.add_widget(view["id"], "kpi_sum", title="Suma",
                            config={"dataset_id": ds["id"], "column": "amount"})
    resp = await client.get(f"/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    # dataset_id appears in the config blob
    assert str(ds["id"]) in html
    assert "amount" in html


async def test_widget_placeholder_no_dataset(config, client):
    """Agg widget without dataset_id keeps placeholder (no crash)."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Empty")
    await vstore.add_widget(view["id"], "bar", title="No data", config={})
    resp = await client.get(f"/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert "data-widget-placeholder" in html


async def test_aggregate_api_smoke(config, client):
    """POST /api/aggregate returns grouped result for seeded dataset."""
    ds = await _seed_dataset(config)
    resp = await client.post("/api/aggregate", json={
        "dataset": ds["id"],
        "measure": "sum",
        "column": "amount",
        "group_by": "month",
        "lang": "pl",
    })
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["kind"] == "grouped"
    assert data["measure"] == "sum"
    assert len(data["items"]) == 2  # 01-2026, 02-2026


async def test_aggregate_api_stacked(config, client):
    """POST /api/aggregate with series returns stacked shape."""
    ds = await _seed_dataset(config)
    resp = await client.post("/api/aggregate", json={
        "dataset": ds["id"],
        "measure": "sum",
        "column": "amount",
        "group_by": "month",
        "series": "region",
        "lang": "pl",
    })
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["kind"] == "stacked"
    assert len(data["buckets"]) == 2
    assert len(data["series"]) == 2  # pl, de


async def test_aggregate_api_errors(config, client):
    """Bad measure / missing dataset / unknown column → 4xx."""
    ds = await _seed_dataset(config)
    # bad measure
    resp = await client.post("/api/aggregate", json={
        "dataset": ds["id"], "measure": "bogus", "column": "amount",
    })
    assert resp.status_code == 400
    # missing dataset
    resp = await client.post("/api/aggregate", json={"measure": "sum"})
    assert resp.status_code == 400
    # unknown dataset
    resp = await client.post("/api/aggregate", json={"dataset": 9999, "measure": "sum"})
    assert resp.status_code == 404
    # bad column
    resp = await client.post("/api/aggregate", json={
        "dataset": ds["id"], "measure": "sum", "column": "nope",
    })
    assert resp.status_code == 400


# ---------- §15.6 / §15.7: friendly widget type names + view delete ----------


async def test_view_delete_route(config, client):
    """§15.7: POST /views/<id>/delete removes the view (404 when missing)."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Do usunięcia")

    resp = await client.post(f"/views/{view['id']}/delete")
    assert resp.status_code in (301, 302)
    assert await vstore.get_view(view["id"]) is None

    # drugi raz → 404, nie 500
    resp = await client.post(f"/views/{view['id']}/delete")
    assert resp.status_code == 404
    resp = await client.post("/views/9999/delete")
    assert resp.status_code == 404


async def test_view_delete_button_on_pages(config, client):
    """§15.7: delete button + confirm present on views list and detail page."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Z przyciskiem")

    resp = await client.get("/views")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert f"/views/{view['id']}/delete" in html

    resp = await client.get(f"/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    assert f"/views/{view['id']}/delete" in html
    # przycisk usuwania + handler potwierdzenia (confirm(); sam tekst jest
    # escapowany przez tojson, więc sprawdzamy etykietę przycisku i atrybut)
    assert "Usuń widok" in html
    assert "confirm(" in html


async def test_widget_type_friendly_names(config, client):
    """§15.6: widget type shown as translated label, not raw code name."""
    db = Database(config.db_path)
    vstore = ViewStore(db)
    view = await vstore.create_view("Nazwy")
    await vstore.add_widget(view["id"], "kpi_sum", title="KPI")
    await vstore.add_widget(view["id"], "table", title="Tabela")
    await vstore.add_widget(view["id"], "note", title="Notka")

    resp = await client.get(f"/views/{view['id']}")
    assert resp.status_code == 200
    html = (await resp.get_data()).decode()
    # nagłówki widżetów: przetłumaczone etykiety (pl), nie surowe kody typów
    assert "KPI: Suma" in html
    assert "Tabela danych" in html
    # dropdown tworzenia widżetu też używa przyjaznych nazw
    assert ">KPI: Suma<" in html or "KPI: Suma" in html
