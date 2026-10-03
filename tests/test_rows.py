"""F3: row storage — type validation, formula engine, CRUD, filters."""

from __future__ import annotations

import pytest

from app.catalog.types import COLUMN_TYPES
from app.db import Database, run_migrations
from app.rows import formula
from app.rows.validators import VALIDATORS


@pytest.fixture
async def rows_db(tmp_path):
    db = Database(tmp_path / "rows.db")
    await run_migrations(db)
    return db


async def _earnings_dataset(db):
    from app.catalog.store import CatalogStore

    store = CatalogStore(db)
    ds = await store.create_dataset("earnings", "Zarobki")
    await store.add_column(ds["id"], "month", "Miesiąc", "year-month", {"input_format": "MM-YYYY"}, 1)
    await store.add_column(ds["id"], "source", "Źródło", "text", {}, 2)
    await store.add_column(ds["id"], "kind", "Typ", "select", {
        "options": [
            {"key": "invoice", "label": {"en": "Invoice", "pl": "Faktura"}},
            {"key": "salary", "label": {"en": "Salary", "pl": "Umowa"}},
        ]
    }, 3)
    await store.add_column(ds["id"], "amount", "Kwota", "currency", {"currency_code": "PLN"}, 4)
    await store.add_column(ds["id"], "vat", "VAT", "formula", {"expression": "round(amount * 0.23, 2)"}, 5)
    return await store.get_dataset(dataset_id=ds["id"])


# ---------- validators ----------


@pytest.mark.parametrize("bad", ["00-2020", "13-2020", "01/2020", "2020-01", "1/2020", "aa-bb"])
def test_year_month_rejects_bad_formats(bad):
    with pytest.raises(ValueError):
        VALIDATORS["year-month"](bad, {})


def test_year_month_normalizes_and_sortkey():
    assert VALIDATORS["year-month"]("4-2026", {}) == ("04-2026", 202604)
    assert VALIDATORS["year-month"]("12.2024", {"input_format": "MM.YYYY"}) == ("12-2024", 202412)


def test_select_validator_checks_options():
    cfg = {"options": [{"key": "a", "label": {"en": "A", "pl": "A"}}]}
    assert VALIDATORS["select"]("a", cfg) == "a"
    with pytest.raises(ValueError):
        VALIDATORS["select"]("b", cfg)
    with pytest.raises(ValueError):
        VALIDATORS["select"]("a", {})


def test_basic_type_coercion():
    assert VALIDATORS["bool"](True, {}) == 1
    assert VALIDATORS["currency"](3, {"currency_code": "PLN"}) == 3.0
    assert VALIDATORS["integer"](7, {}) == 7
    with pytest.raises(ValueError):
        VALIDATORS["integer"](True, {})
    with pytest.raises(ValueError):
        VALIDATORS["float"]("x", {})


# ---------- formula engine ----------


def test_formula_referenced_columns():
    assert formula.referenced_columns("round({amount} * vat_rate, 2)") == ["amount", "vat_rate"]
    assert formula.referenced_columns("not python (") == []


def test_formula_evaluate_ok():
    assert formula.evaluate("a + b * 2", {"a": 1.5, "b": 2}) == 5.5
    assert formula.evaluate("round(x * 0.23, 2)", {"x": 100}) == 23.0
    assert formula.evaluate("{salary} + {side}", {"salary": 9000, "side": 800}) == 9800.0


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "a if b else c",
        "[x for x in y]",
        "lambda: 1",
    ],
)
def test_formula_evaluate_rejects_hostile(expr):
    with pytest.raises((ValueError, SyntaxError)):
        formula.evaluate(expr, {"a": 1, "b": 2, "x": 1, "y": [1]})


def test_recompute_formulas_uses_row():
    cols = [
        {"key": "amount", "type": "currency", "config": {"currency_code": "PLN"}},
        {"key": "vat", "type": "formula", "config": {"expression": "amount * 0.23"}},
        {"key": "broken", "type": "formula", "config": {"expression": "nope * 2"}},
    ]
    out = formula.recompute_formulas({"amount": 100.0}, cols)
    assert out["vat"] == pytest.approx(23.0)
    assert out["broken"] is None


async def test_formula_column_backfilled_for_existing_rows(rows_db):
    """Adding a formula column after rows exist must fill their cached values,
    not leave NULLs rendering as '-'."""
    from app.catalog.store import CatalogStore
    from app.rows.store import RowStore

    store = CatalogStore(rows_db)
    ds = await store.create_dataset("backfill", "Backfill")
    await store.add_column(ds["id"], "amount", "Kwota", "currency", {"currency_code": "PLN"}, 1)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(rows_db)
    await rs.create_row(ds, {"amount": 1200})
    await rs.create_row(ds, {"amount": 600})

    col = await store.add_column(
        ds["id"], "half", "Połowa", "formula", {"expression": "amount / 2"}, 2
    )
    ds = await store.get_dataset(dataset_id=ds["id"])
    rows = (await rs.list_rows(ds))["items"]
    assert sorted(r[col["key"]] for r in rows) == [300.0, 600.0]


# ---------- row store CRUD ----------


async def test_row_crud_and_shadow(rows_db):
    from app.rows.store import RowStore

    ds = await _earnings_dataset(rows_db)
    rs = RowStore(rows_db)
    row = await rs.create_row(ds, {
        "month": "4-2026",
        "source": "UoP",
        "kind": "salary",
        "amount": 9000,
    })
    assert row["id"] == 1
    assert row["month"] == "04-2026"
    assert row["month__sort_key"] == 202604
    assert row["vat"] == pytest.approx(2070.0)
    assert "created_at" in row and "updated_at" in row

    updated = await rs.update_row(ds, row["id"], {"amount": 10000, "source": "UoP2"})
    assert updated["vat"] == pytest.approx(2300.0)
    assert updated["source"] == "UoP2"
    assert updated["updated_at"] >= row["updated_at"]

    assert await rs.delete_row(ds, row["id"]) is True
    assert await rs.get_row(ds, row["id"]) is None
    assert await rs.delete_row(ds, row["id"]) is False


async def test_row_validation_error(rows_db):
    from app.rows.store import RowStore

    ds = await _earnings_dataset(rows_db)
    rs = RowStore(rows_db)
    with pytest.raises(ValueError, match="select"):
        await rs.create_row(ds, {"kind": "cash"})
    with pytest.raises(ValueError, match="year-month"):
        await rs.create_row(ds, {"month": "2026-04"})
    with pytest.raises(ValueError, match="number|float"):
        await rs.create_row(ds, {"amount": "dużo"})


async def test_row_filters_sort_pagination(rows_db):
    from app.rows.store import RowStore

    ds = await _earnings_dataset(rows_db)
    rs = RowStore(rows_db)
    data = [
        ("01-2026", "UoP", "salary", 9000),
        ("02-2026", "UoP", "salary", 9000),
        ("03-2026", "B2B", "invoice", 5500),
        ("04-2026", "B2B", "invoice", 7000),
    ]
    for month, source, kind, amount in data:
        await rs.create_row(ds, {"month": month, "source": source, "kind": kind, "amount": amount})

    # eq + gte filters on logical keys
    page = await rs.list_rows(ds, filters={"kind": {"eq": "invoice"}, "amount": {"gte": 6000}})
    assert page["total"] == 1 and page["items"][0]["amount"] == 7000.0

    # contains on text
    page = await rs.list_rows(ds, filters={"source": {"contains": "oP"}})
    assert page["total"] == 2

    # year-month chronological sort via shadow field
    page = await rs.list_rows(ds, sort="-month")
    assert [r["month"] for r in page["items"]] == ["04-2026", "03-2026", "02-2026", "01-2026"]

    # pagination
    page = await rs.list_rows(ds, page=2, page_size=2, sort="month")
    assert page["total"] == 4
    assert [r["month"] for r in page["items"]] == ["03-2026", "04-2026"]

    # invalid pagination
    with pytest.raises(ValueError):
        await rs.list_rows(ds, page=0)
    with pytest.raises(ValueError):
        await rs.list_rows(ds, page_size=501)


# ---------- API ----------


async def test_rows_api_endpoints(client):
    r = await client.post("/api/datasets", json={"slug": "income", "name": "Income"})
    assert r.status_code == 201
    ds_id = (await r.get_json())["id"]
    await client.post(f"/api/datasets/{ds_id}/columns", json={
        "key": "month", "label": "Month", "type": "year-month", "config": {"input_format": "MM-YYYY"},
    })
    await client.post(f"/api/datasets/{ds_id}/columns", json={
        "key": "amount", "label": "Amount", "type": "currency", "config": {"currency_code": "PLN"},
    })
    await client.post(f"/api/datasets/{ds_id}/columns", json={
        "key": "vat", "label": "VAT", "type": "formula", "config": {"expression": "amount * 0.23"},
    })

    r = await client.post(f"/api/datasets/{ds_id}/rows", json={"month": "05-2026", "amount": 1234})
    assert r.status_code == 201
    row = await r.get_json()
    assert row["vat"] == pytest.approx(283.82)
    row_id = row["id"]

    r = await client.get(f"/api/datasets/{ds_id}/rows?f.amount.gte=1000&sort=-month")
    data = await r.get_json()
    assert data["total"] == 1 and data["items"][0]["id"] == row_id

    r = await client.patch(f"/api/datasets/{ds_id}/rows/{row_id}", json={"amount": 2000})
    assert (await r.get_json())["vat"] == pytest.approx(460.0)

    r = await client.post(f"/api/datasets/{ds_id}/rows", json={"month": "2026-05", "amount": 1})
    assert r.status_code == 400

    r = await client.delete(f"/api/datasets/{ds_id}/rows/{row_id}")
    assert r.status_code == 200
    assert (await client.get(f"/api/datasets/{ds_id}/rows")).status_code == 200
    assert (await (await client.get(f"/api/datasets/{ds_id}/rows")).get_json())["total"] == 0

    assert (await client.get("/api/datasets/999/rows")).status_code == 404
