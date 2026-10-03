"""F4: aggregation engine — measures, group-by, series, filters, select sort."""

from __future__ import annotations

import pytest

from app.catalog.store import CatalogStore
from app.db import Database, run_migrations
from app.rows.store import RowStore


@pytest.fixture
async def agg_db(tmp_path):
    db = Database(tmp_path / "agg.db")
    await run_migrations(db)
    return db


async def _seed(db):
    store = CatalogStore(db)
    ds = await store.create_dataset("earnings", "Zarobki")
    await store.add_column(ds["id"], "month", "Miesiąc", "year-month", {"input_format": "MM-YYYY"}, 1)
    await store.add_column(ds["id"], "source", "Źródło", "select", {
        "options": [
            {"key": "uop", "label": {"en": "Contract", "pl": "Umowa"}, "color": "#3b82f6"},
            {"key": "b2b", "label": {"en": "B2B Invoice", "pl": "Faktura B2B"}, "color": "#f59e0b"},
        ]
    }, 2)
    await store.add_column(ds["id"], "amount", "Kwota", "currency", {"currency_code": "PLN"}, 3)

    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(db)
    rows = [
        ("01-2026", "uop", 9000), ("02-2026", "uop", 9000),
        ("03-2026", "uop", 6000), ("03-2026", "b2b", 8000),
        ("04-2026", "b2b", 12000), ("05-2026", "b2b", 4000),
    ]
    for month, source, amount in rows:
        await rs.create_row(ds, {"month": month, "source": source, "amount": amount})
    return await store.get_dataset(dataset_id=ds["id"])


# ---------- scalar ----------


async def test_scalar_sum_count_avg(agg_db):
    from unittest.mock import patch as _patch_module  # noqa: F401

    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {"measure": "sum", "column": "amount"})
    assert result["kind"] == "scalar"
    assert result["value"] == pytest.approx(48000.0)

    result = await aggregate(agg_db, ds, {"measure": "count"})
    assert result["value"] == 6

    result = await aggregate(agg_db, ds, {"measure": "avg", "column": "amount"})
    assert result["value"] == pytest.approx(8000.0)

    result = await aggregate(agg_db, ds, {"measure": "min", "column": "amount"})
    assert result["value"] == 4000.0
    result = await aggregate(agg_db, ds, {"measure": "max", "column": "amount"})
    assert result["value"] == 12000.0


async def test_avg_per_scalar_per_column_variants(agg_db):
    """avg_per = SUM(column) / COUNT(DISTINCT per_column) — e.g. sum ÷ months."""
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "avg_per", "column": "amount", "per_column": "month",
    })
    assert result["kind"] == "scalar"
    # seeded months: 01..05 → 5 distinct
    assert result["value"] == pytest.approx(48000.0 / 5)

    # any column type works as the divisor — here a select column (2 options)
    result = await aggregate(agg_db, ds, {
        "measure": "avg_per", "column": "amount", "per_column": "source",
    })
    assert result["value"] == pytest.approx(48000.0 / 2)


async def test_avg_per_grouped_by_year_partial_year_counts_present_months(agg_db):
    """The original use case: 2 records/month, avg per month grouped by year.
    A year with data only for some months divides by those months, not 12."""
    from app.aggregation import aggregate

    store = CatalogStore(agg_db)
    ds = await store.create_dataset("monthly", "Miesięczne")
    await store.add_column(ds["id"], "year", "Rok", "year", {}, 1)
    await store.add_column(ds["id"], "month", "Miesiąc", "year-month", {"input_format": "MM-YYYY"}, 2)
    await store.add_column(ds["id"], "amount", "Kwota", "currency", {"currency_code": "PLN"}, 3)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(agg_db)
    # 2025: 12 months × 2 records of 500 → yearSum ÷ 12 = 1000
    for m in range(1, 13):
        for _ in range(2):
            await rs.create_row(ds, {"year": 2025, "month": f"{m:02d}-2025", "amount": 500})
    # 2026: 3 months × 2 records of 100 → present-months avg = 200 (not /12 = 50)
    for m in range(1, 4):
        for _ in range(2):
            await rs.create_row(ds, {"year": 2026, "month": f"{m:02d}-2026", "amount": 100})

    result = await aggregate(agg_db, ds, {
        "measure": "avg_per", "column": "amount", "per_column": "month",
        "group_by": "year",
    })
    assert result["kind"] == "grouped"
    values = {it["key"]: it["value"] for it in result["items"]}
    assert values[2025] == pytest.approx(1000.0)
    assert values[2026] == pytest.approx(200.0)


async def test_avg_per_missing_per_column(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    with pytest.raises(ValueError):
        await aggregate(agg_db, ds, {"measure": "avg_per", "column": "amount"})
    with pytest.raises(ValueError):
        await aggregate(agg_db, ds, {
            "measure": "avg_per", "column": "amount", "per_column": "nope",
        })


async def test_scalar_median_odd_even(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {"measure": "median", "column": "amount"})
    assert result["value"] == pytest.approx(8500.0)

    await RowStore(agg_db).create_row(ds, {"month": "06-2026", "source": "uop", "amount": 1})
    result = await aggregate(agg_db, ds, {"measure": "median", "column": "amount"})
    # sorted [1, 4000, 6000, 8000, 9000, 9000, 12000] → median 8000
    assert result["value"] == pytest.approx(8000.0)


async def test_bad_measure(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    with pytest.raises(ValueError):
        await aggregate(agg_db, ds, {"measure": "bogus", "column": "amount"})
    with pytest.raises(ValueError):
        await aggregate(agg_db, ds, {"measure": "sum", "column": "nope"})


# ---------- filters ----------


async def test_filters_eq_contains(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "filters": {"source": {"eq": "b2b"}},
    })
    assert result["value"] == pytest.approx(24000.0)

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "filters": {"month": {"contains": "2026"}},
    })
    assert result["value"] == pytest.approx(48000.0)


# ---------- group_by ----------


async def test_group_year_month_chronological(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "group_by": "month",
    })
    assert result["kind"] == "grouped"
    keys = [it["key"] for it in result["items"]]
    assert keys == ["01-2026", "02-2026", "03-2026", "04-2026", "05-2026"]
    values = [it["value"] for it in result["items"]]
    assert values == pytest.approx([9000.0, 9000.0, 14000.0, 12000.0, 4000.0])


async def test_group_select_order_labels(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "group_by": "source",
    })
    keys = [it["key"] for it in result["items"]]
    # Option order from config, not alphabetical (b2b would win)
    assert keys == ["uop", "b2b"]
    assert result["items"][0]["label"] == "Contract"

    result_pl = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "group_by": "source", "lang": "pl",
    })
    assert result_pl["items"][0]["label"] == "Umowa"


async def test_group_composite_two_columns(agg_db):
    """§15.12: group_by accepts a list — month + source composite buckets,
    ordered by the first column (temporal) then the second (select rank)."""
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "group_by": ["month", "source"],
    })
    assert result["kind"] == "grouped"
    keys = [it["key"] for it in result["items"]]
    assert keys == [
        "01-2026 uop", "02-2026 uop", "03-2026 uop", "03-2026 b2b",
        "04-2026 b2b", "05-2026 b2b",
    ]
    labels = [it["label"] for it in result["items"]]
    assert "Contract" in labels[0]          # joined per-column labels
    assert "B2B Invoice" in labels[3]
    values = [it["value"] for it in result["items"]]
    assert values == pytest.approx([9000.0, 9000.0, 6000.0, 8000.0, 12000.0, 4000.0])
    # composite sort is per-column (list), not a single scalar
    assert isinstance(result["items"][0]["sort"], list)

    with pytest.raises(ValueError):
        await aggregate(agg_db, ds, {
            "measure": "sum", "column": "amount", "group_by": ["month", "nope"],
        })


async def test_group_month_select_over_year(agg_db):
    """§15.12: month (select) grouped over year — composite buckets give a
    chronological month+year timeline axis."""
    from app.catalog.store import CatalogStore
    from app.rows.store import RowStore

    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    store = CatalogStore(agg_db)
    ds = await store.create_dataset("timeline", "Oś czasu")
    await store.add_column(ds["id"], "year", "Rok", "year", {}, 1)
    await store.add_column(ds["id"], "month", "Miesiąc", "select", {
        "options": [
            {"key": f"{m:02d}", "label": month_names[m - 1]}
            for m in range(1, 13)
        ]
    }, 2)
    await store.add_column(ds["id"], "amount", "Kwota", "integer", {}, 3)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(agg_db)
    for year, month, amount in [(2025, "12", 100), (2026, "02", 150), (2026, "01", 200)]:
        await rs.create_row(ds, {"year": year, "month": month, "amount": amount})
    ds = await store.get_dataset(dataset_id=ds["id"])

    from app.aggregation import aggregate
    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "group_by": ["year", "month"],
    })
    keys = [it["key"] for it in result["items"]]
    # chronological: 2025-12 < 2026-01 < 2026-02 (select rank, not alphabet)
    assert keys == ["2025 12", "2026 01", "2026 02"]
    values = [it["value"] for it in result["items"]]
    assert values == [100, 200, 150]
    labels = [it["label"] for it in result["items"]]
    assert "December" in labels[0] and "January" in labels[1] and "February" in labels[2]


async def test_group_select_string_labels(agg_db):
    """Select options with plain-string labels resolve correctly (point 5)."""
    from app.catalog.store import CatalogStore
    from app.rows.store import RowStore

    store = CatalogStore(agg_db)
    ds = await store.create_dataset("simple", "Proste")
    await store.add_column(ds["id"], "kind", "Typ", "select", {
        "options": [
            {"key": "s", "label": "Small"},
            {"key": "l", "label": "Large"},
        ]
    }, 1)
    await store.add_column(ds["id"], "n", "N", "integer", {}, 2)
    ds = await store.get_dataset(dataset_id=ds["id"])
    rs = RowStore(agg_db)
    for kind, n in [("s", 3), ("l", 7), ("s", 2)]:
        await rs.create_row(ds, {"kind": kind, "n": n})
    ds = await store.get_dataset(dataset_id=ds["id"])

    from app.aggregation import aggregate
    result = await aggregate(agg_db, ds, {"measure": "sum", "column": "n", "group_by": "kind"})
    keys = [it["key"] for it in result["items"]]
    assert keys == ["s", "l"]
    assert result["items"][0]["label"] == "Small"
    assert result["items"][1]["label"] == "Large"
    # string label used for any lang
    result_pl = await aggregate(agg_db, ds, {"measure": "sum", "column": "n", "group_by": "kind", "lang": "pl"})
    assert result_pl["items"][0]["label"] == "Small"


# ---------- series (stacked) ----------


async def test_stacked_month_source(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "group_by": "month", "series": "source",
    })
    assert result["kind"] == "stacked"
    keys = [s["key"] for s in result["series"]]
    assert keys == ["uop", "b2b"]
    assert result["series"][0]["color"] == "#3b82f6"
    assert result["series"][0]["label"] == "Contract"
    # Jan has only UoP; Feb only UoP; Mar both; Apr only b2b; May only b2b
    assert result["series"][0]["values"] == pytest.approx([9000.0, 9000.0, 6000.0, None, None])


# ---------- filters ----------


async def test_filters_with_in_and_lt(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "filters": [{"column": "month", "op": "in", "value": ["01-2026", "02-2026"]}],
    })
    assert result["value"] == pytest.approx(18000.0)

    result = await aggregate(agg_db, ds, {
        "measure": "sum", "column": "amount",
        "filters": [{"column": "amount", "op": "lt", "value": 5000}],
    })
    assert result["value"] == pytest.approx(4000.0)


async def test_bad_filter_column(agg_db):
    ds = await _seed(agg_db)
    from app.aggregation import aggregate

    with pytest.raises(ValueError):
        await aggregate(agg_db, ds, {
            "measure": "sum", "column": "amount",
            "filters": {"nope": {"eq": 1}},
        })


# ---------- api ----------


async def test_api_scalar(config, client):
    ds = await _seed(Database(config.db_path))
    resp = await client.post("/api/aggregate", json={
        "dataset": ds["slug"], "measure": "sum", "column": "amount",
    })
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["kind"] == "scalar"
    assert data["value"] == pytest.approx(48000.0)


async def test_api_by_slug_and_stacked(config, client):
    ds = await _seed(Database(config.db_path))
    resp = await client.post("/api/aggregate", json={
        "dataset": "earnings", "measure": "sum", "column": "amount",
        "group_by": "month", "series": "source",
    })
    assert resp.status_code == 200
    data = await resp.get_json()
    assert data["kind"] == "stacked"
    assert data["series"][0]["label"] == "Contract"


async def test_api_errors(config, client):
    ds = await _seed(Database(config.db_path))
    resp = await client.post("/api/aggregate", json={"dataset": "nope"})
    assert resp.status_code == 404

    resp = await client.post("/api/aggregate", json={"dataset": "earnings", "measure": "bogus"})
    assert resp.status_code == 400

    resp = await client.post("/api/aggregate", json={"dataset": "earnings", "measure": "sum", "column": "nope"})
    assert resp.status_code == 400
