"""REST endpoints for views & widgets (F5).

Route shapes follow todo.md §11; /views/<id> includes its widgets (ordered),
/widgets routes are standalone like /columns in the datasets API.
"""

from __future__ import annotations

from typing import Any

from quart import Blueprint, jsonify, request

from ..db import get_db
from ..views.store import ViewStore

bp = Blueprint("views_api", __name__)  # prefix /api comes from the parent blueprint


def _store() -> ViewStore:
    return ViewStore(get_db())


# ---------- views ----------


@bp.get("/views")
async def list_views() -> Any:
    return jsonify(await _store().list_views())


@bp.post("/views")
async def create_view() -> Any:
    data = await request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    if not isinstance(data.get("settings") or {}, dict):
        return jsonify({"error": "settings must be an object"}), 400
    try:
        view = await _store().create_view(
            name,
            icon=str(data.get("icon", "")),
            theme=str(data.get("theme", "")),
            settings=data.get("settings"),
            position=int(data.get("position") or 0),
        )
        return jsonify(view), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.get("/views/<int:view_id>")
async def get_view(view_id: int) -> Any:
    store = _store()
    view = await store.get_view(view_id)
    if not view:
        return jsonify({"error": "view not found"}), 404
    view["widgets"] = await store.list_widgets(view_id)
    return jsonify(view)


@bp.patch("/views/<int:view_id>")
async def update_view(view_id: int) -> Any:
    data = await request.get_json(silent=True) or {}
    if "settings" in data and not isinstance(data["settings"], dict):
        return jsonify({"error": "settings must be an object"}), 400
    try:
        view = await _store().update_view(
            view_id,
            name=data.get("name"),
            icon=data.get("icon"),
            theme=data.get("theme"),
            settings=data.get("settings"),
            position=data.get("position"),
        )
        return jsonify(view)
    except KeyError:
        return jsonify({"error": "view not found"}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.delete("/views/<int:view_id>")
async def delete_view(view_id: int) -> Any:
    try:
        await _store().delete_view(view_id)
        return jsonify({"deleted": view_id})
    except KeyError:
        return jsonify({"error": "view not found"}), 404


# ---------- widgets ----------


@bp.get("/views/<int:view_id>/widgets")
async def list_widgets(view_id: int) -> Any:
    store = _store()
    if not await store.get_view(view_id):
        return jsonify({"error": "view not found"}), 404
    return jsonify(await store.list_widgets(view_id))


@bp.post("/views/<int:view_id>/widgets")
async def add_widget(view_id: int) -> Any:
    store = _store()
    if not await store.get_view(view_id):
        return jsonify({"error": "view not found"}), 404
    data = await request.get_json(silent=True) or {}
    widget_type = str(data.get("type", "")).strip()
    if not widget_type:
        return jsonify({"error": "type required"}), 400
    geometry = {k: data.get(k) for k in ("x", "y", "w", "h", "position") if k in data}
    if "config" in data and not isinstance(data["config"], dict):
        return jsonify({"error": "config must be an object"}), 400
    try:
        widget = await store.add_widget(
            view_id,
            widget_type,
            title=str(data.get("title", "")),
            config=data.get("config"),
            geometry=geometry,
        )
        return jsonify(widget), 201
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.put("/views/<int:view_id>/layout")
async def save_layout(view_id: int) -> Any:
    """Bulk gridstack save: body = [{"id", "x", "y", "w", "h", "position"}]."""
    store = _store()
    if not await store.get_view(view_id):
        return jsonify({"error": "view not found"}), 404
    data = await request.get_json(silent=True)
    layout = (data or {}).get("layout") if isinstance(data, dict) else data
    if not isinstance(layout, list):
        return jsonify({"error": "layout must be a list of widget geometries"}), 400
    try:
        return jsonify(await store.set_layout(view_id, layout))
    except KeyError as exc:
        return jsonify({"error": str(exc).strip("'")}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.patch("/widgets/<int:widget_id>")
async def update_widget(widget_id: int) -> Any:
    data = await request.get_json(silent=True) or {}
    if "config" in data and not isinstance(data["config"], dict):
        return jsonify({"error": "config must be an object"}), 400
    geometry = {k: data[k] for k in ("x", "y", "w", "h", "position") if k in data}
    try:
        widget = await _store().update_widget(
            widget_id,
            title=data.get("title"),
            config=data.get("config"),
            widget_type=data.get("type"),
            geometry=geometry,
        )
        return jsonify(widget)
    except KeyError:
        return jsonify({"error": "widget not found"}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400


@bp.delete("/widgets/<int:widget_id>")
async def delete_widget(widget_id: int) -> Any:
    try:
        await _store().delete_widget(widget_id)
        return jsonify({"deleted": widget_id})
    except KeyError:
        return jsonify({"error": "widget not found"}), 404
