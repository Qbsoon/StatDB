"""REST endpoints for dataset/column schema management."""

from __future__ import annotations

import json
from typing import Any

from quart import Blueprint, current_app, g, jsonify, request

from ..catalog.migrations import SLUG_RE
from ..catalog.store import CatalogStore
from ..db import get_db

bp = Blueprint("catalog_api", __name__)  # prefix /api comes from the parent blueprint


def _store() -> CatalogStore:
    return CatalogStore(get_db())


@bp.get("/datasets")
async def list_datasets() -> Any:
    try:
        return jsonify(await _store().list_datasets())
    except Exception as exc:
        current_app.logger.exception("datasets list failed")
        return jsonify({"error": str(exc)}), 500


@bp.post("/datasets")
async def create_dataset() -> Any:
    data = await request.get_json(silent=True) or {}
    slug = str(data.get("slug", "")).strip().lower()
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    if not slug or not SLUG_RE.match(slug):
        return jsonify({"error": "Invalid slug (lowercase letters/digits/underscore, start with letter)"}), 400
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        ds = await _store().create_dataset(slug=slug, name=name, description=description)
        return jsonify(ds), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409


@bp.get("/datasets/<int:dataset_id>")
async def get_dataset(dataset_id: int) -> Any:
    ds = await _store().get_dataset(dataset_id=dataset_id)
    if not ds:
        return jsonify({"error": "dataset not found"}), 404
    return jsonify(ds)


@bp.patch("/datasets/<int:dataset_id>")
async def update_dataset(dataset_id: int) -> Any:
    data = await request.get_json(silent=True) or {}
    try:
        ds = await _store().update_dataset(
            dataset_id,
            name=data.get("name"),
            description=data.get("description"),
        )
        return jsonify(ds)
    except KeyError:
        return jsonify({"error": "dataset not found"}), 404


@bp.delete("/datasets/<int:dataset_id>")
async def delete_dataset(dataset_id: int) -> Any:
    ds = await _store().get_dataset(dataset_id=dataset_id)
    if not ds:
        return jsonify({"error": "dataset not found"}), 404
    await _store().delete_dataset(dataset_id)
    return jsonify({"deleted": dataset_id})


@bp.post("/datasets/<int:dataset_id>/columns")
async def add_column(dataset_id: int) -> Any:
    data = await request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip().lower().replace(" ", "_")
    label = str(data.get("label", "")).strip()
    type_key = str(data.get("type", "")).strip()
    config = data.get("config")
    if not isinstance(config, dict):
        config = {}
    try:
        col = await _store().add_column(
            dataset_id,
            key=key,
            label=label or key.replace("_", " ").title(),
            type_key=type_key,
            config=config,
            position=data.get("position"),
        )
        return jsonify(col), 201
    except KeyError:
        return jsonify({"error": "dataset not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.patch("/columns/<int:column_id>")
async def update_column(column_id: int) -> Any:
    data = await request.get_json(silent=True) or {}
    try:
        col = await _store().update_column(
            column_id, label=data.get("label"), config=data.get("config")
        )
        return jsonify(col)
    except KeyError:
        return jsonify({"error": "column not found"}), 404


@bp.delete("/columns/<int:column_id>")
async def remove_column(column_id: int) -> Any:
    try:
        await _store().remove_column(column_id)
        return jsonify({"deleted": column_id})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/datasets/presets/months")
async def months_preset() -> Any:
    data = await request.get_json(silent=True) or {}
    year_from = int(data.get("year_from", 2020))
    year_to = int(data.get("year_to", 2030))
    if year_from > year_to or year_to - year_from > 50:
        return jsonify({"error": "year_from must be ≤ year_to and span ≤ 50 years"}), 400
    ds = await _store().create_months_preset(year_from, year_to)
    return jsonify(ds), 201
