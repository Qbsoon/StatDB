"""REST endpoints for row CRUD with validation, filters and pagination.

Nested under /api/datasets/<id>/rows. Filters come as repeated query args:
``?f.<column>.<op>=value`` (ops: eq, ne, lt, lte, gt, gte, contains),
sorting via ``?sort=<column>`` or ``?sort=-<column>`` (+ = asc explicit).
"""

from __future__ import annotations

from typing import Any

from quart import Blueprint, current_app, jsonify, request

from ..catalog.store import CatalogStore
from ..db import get_db
from ..rows.store import RowStore

bp = Blueprint("rows_api", __name__)

OPS = {"eq", "ne", "lt", "lte", "gt", "gte", "contains"}


async def _load_dataset(dataset_id: int) -> dict[str, Any] | None:
    return await CatalogStore(get_db()).get_dataset(dataset_id=dataset_id)


def _parse_filters(args: Any) -> dict[str, dict[str, Any]]:
    filters: dict[str, dict[str, Any]] = {}
    for key in args.keys():
        if not key.startswith("f."):
            continue
        _, col_key, op = key.split(".", 2)
        filters.setdefault(col_key, {})[op] = args[key]
    return filters


@bp.get("/datasets/<int:dataset_id>/rows")
async def list_rows(dataset_id: int) -> Any:
    dataset = await _load_dataset(dataset_id)
    if not dataset:
        return jsonify({"error": "dataset not found"}), 404
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 50))
        data = await RowStore(get_db()).list_rows(
            dataset,
            page=page,
            page_size=page_size,
            filters=_parse_filters(request.args),
            sort=request.args.get("sort"),
        )
        return jsonify(data)
    except ValueError as exc:
        current_app.logger.warning("rows list rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@bp.post("/datasets/<int:dataset_id>/rows")
async def create_row(dataset_id: int) -> Any:
    dataset = await _load_dataset(dataset_id)
    if not dataset:
        return jsonify({"error": "dataset not found"}), 404
    body = await request.get_json(silent=True) or {}
    try:
        row = await RowStore(get_db()).create_row(dataset, body)
        return jsonify(row), 201
    except ValueError as exc:
        current_app.logger.warning("row create rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@bp.get("/rows/<int:row_id>")
async def get_row(row_id: int) -> Any:  # pragma: no cover - needs dataset context; use PATCH path
    return jsonify({"error": "fetch via PATCH/DELETE identifier or list endpoint"}), 400


@bp.patch("/datasets/<int:dataset_id>/rows/<int:row_id>")
async def update_row(dataset_id: int, row_id: int) -> Any:
    dataset = await _load_dataset(dataset_id)
    if not dataset:
        return jsonify({"error": "dataset not found"}), 404
    body = await request.get_json(silent=True) or {}
    try:
        row = await RowStore(get_db()).update_row(dataset, row_id, body)
        return jsonify(row)
    except KeyError:
        return jsonify({"error": "row not found"}), 404
    except ValueError as exc:
        current_app.logger.warning("row update rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@bp.delete("/datasets/<int:dataset_id>/rows/<int:row_id>")
async def delete_row(dataset_id: int, row_id: int) -> Any:
    dataset = await _load_dataset(dataset_id)
    if not dataset:
        return jsonify({"error": "dataset not found"}), 404
    ok = await RowStore(get_db()).delete_row(dataset, row_id)
    if not ok:
        return jsonify({"error": "row not found"}), 404
    return jsonify({"deleted": row_id})
