"""POST /api/aggregate — generic aggregation over a dataset (F4).

Body:
  {
    "dataset":  <id or slug>,
    "measure":  "sum|avg|count|min|max|median",   # default "sum"
    "column":   "<measure source column>",        # required for non-count
    "group_by": "<column key>",                   # optional
    "series":   "<column key>",                   # optional (needs group_by)
    "filters":  {"<col>": {"<op>": <val>}},       # or list of clauses
    "lang":     "en|pl"                            # select label + months
  }
"""

from __future__ import annotations

from typing import Any

from quart import Blueprint, jsonify, request

from ..aggregation import aggregate
from ..catalog.store import CatalogStore
from ..db import get_db

bp = Blueprint("aggregate_api", __name__)


@bp.post("/aggregate")
async def run_aggregate() -> Any:
    body = await request.get_json(silent=True) or {}
    ds_ref = body.get("dataset")
    if ds_ref is None:
        return jsonify({"error": "missing dataset"}), 400

    store = CatalogStore(get_db())
    if isinstance(ds_ref, int):
        dataset = await store.get_dataset(dataset_id=ds_ref)
    else:
        dataset = await store.get_dataset(slug=str(ds_ref))
    if not dataset:
        return jsonify({"error": "dataset not found"}), 404

    spec = {
        "measure": body.get("measure", "sum"),
        "column": body.get("column"),
        "group_by": body.get("group_by"),
        "series": body.get("series"),
        "filters": body.get("filters"),
        "lang": body.get("lang", "en"),
    }
    try:
        result = await aggregate(get_db(), dataset, spec)
    except (KeyError, TypeError) as exc:
        return jsonify({"error": f"invalid aggregate request: {exc}"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result), 200
