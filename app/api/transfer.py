"""F10 — Import/export, backup, views config transfer, scheduled snapshots.

REST endpoints:
  POST /api/datasets/import-csv      — upload CSV → new dataset + columns + rows
  GET  /api/datasets/<id>/export     — ?format=csv|json download
  GET  /api/backup                   — download a SQLite backup copy
  GET  /api/views/export             — JSON of all views + widgets
  POST /api/views/import             — JSON → create views + widgets
  POST /api/snapshots/trigger        — manually trigger a snapshot now
  GET  /api/snapshots                — list snapshot files with sizes
  DELETE /api/snapshots/<name>       — delete one snapshot
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quart import Blueprint, current_app, jsonify, request, send_file

from ..catalog.store import CatalogStore
from ..catalog.types import COLUMN_TYPES
from ..db import get_db
from ..rows.store import RowStore
from ..views.store import ViewStore

bp = Blueprint("transfer_api", __name__)

# ---------------------------------------------------------------------------
# Type inference for CSV import
# ---------------------------------------------------------------------------

_INT_RE = __import__("re").compile(r"^-?\d+$")
_FLOAT_RE = __import__("re").compile(r"^-?\d+[.,]\d+$")
_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_YM_RE = __import__("re").compile(r"^\d{2}[-./]\d{4}$")
_BOOL_RE = __import__("re").compile(r"^(true|false|yes|no|tak|nie|1|0)$", __import__("re").I)
_YEAR_RE = __import__("re").compile(r"^(19|20)\d{2}$")


def _infer_type(samples: list[str]) -> str:
    """Pick a logical column type from non-empty sample strings."""
    vals = [v.strip() for v in samples if v.strip()]
    if not vals:
        return "text"
    if all(_BOOL_RE.match(v) for v in vals):
        # only infer bool if values are strictly bool-like and few distinct
        if len(set(v.lower() for v in vals)) <= 2:
            return "bool"
    if all(_YM_RE.match(v) for v in vals):
        return "year-month"
    if all(_YEAR_RE.match(v) for v in vals):
        return "year"
    if all(_DATE_RE.match(v) for v in vals):
        return "date"
    if all(_DATETIME_RE.match(v) for v in vals):
        return "datetime"
    if all(_INT_RE.match(v) for v in vals):
        return "integer"
    # allow Polish decimal comma in float detection
    if all(_FLOAT_RE.match(v) for v in vals):
        return "float"
    return "text"


def _coerce_cell(raw: str, type_key: str) -> Any:
    """Convert CSV string to the Python type expected by RowStore validators."""
    raw = raw.strip()
    if not raw:
        return None
    if type_key == "bool":
        return raw.lower() in ("true", "yes", "tak", "1")
    if type_key in ("integer", "year"):
        try:
            return int(raw)
        except ValueError:
            return raw
    if type_key in ("float", "currency"):
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            return raw
    return raw


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@bp.post("/datasets/import-csv")
async def import_csv() -> Any:
    files = await request.files
    form = await request.form
    upload = files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "no file uploaded"}), 400

    slug = (form.get("slug") or "").strip().lower()
    name = (form.get("name") or "").strip()
    if not slug:
        # derive from filename
        base = Path(upload.filename).stem
        slug = "".join(c if c.isalnum() or c == "_" else "_" for c in base.lower()).strip("_")
        if slug and slug[0].isdigit():
            slug = "ds_" + slug
    if not name:
        name = Path(upload.filename).stem.replace("_", " ").title() or slug

    raw = upload.read().decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(raw))
    try:
        header = next(reader)
    except StopIteration:
        return jsonify({"error": "empty CSV file"}), 400
    header = [h.strip() for h in header]
    data_rows = list(reader)
    if not header:
        return jsonify({"error": "no header row in CSV"}), 400

    # sanitise column keys
    def _safe_key(h: str) -> str:
        k = "".join(c if c.isalnum() or c == "_" else "_" for c in h.lower()).strip("_")
        if k and k[0].isdigit():
            k = "col_" + k
        return k or "col"

    keys = [_safe_key(h) for h in header]
    # deduplicate keys
    seen: dict[str, int] = {}
    for i, k in enumerate(keys):
        if k in seen:
            seen[k] += 1
            keys[i] = f"{k}_{seen[k]}"
        else:
            seen[k] = 1

    # infer types from sample (first 200 non-empty values per column)
    col_samples: list[list[str]] = [[] for _ in header]
    for row in data_rows[:200]:
        for i, cell in enumerate(row[: len(header)]):
            if cell.strip():
                col_samples[i].append(cell)
    types = [_infer_type(s) for s in col_samples]

    store = CatalogStore(get_db())
    try:
        ds = await store.create_dataset(slug, name)
    except (ValueError, KeyError) as exc:
        return jsonify({"error": str(exc)}), 400

    for pos, (key, ty) in enumerate(zip(keys, types), 1):
        label = header[pos - 1] or key
        config: dict[str, Any] = {}
        if ty == "year-month":
            config["input_format"] = "MM-YYYY"
        try:
            await store.add_column(ds["id"], key, label, ty, config, pos)
        except (ValueError, KeyError):
            # if a column fails skip it but keep going
            continue

    ds = await store.get_dataset(dataset_id=ds["id"])
    if not ds:
        return jsonify({"error": "dataset disappeared after creation"}), 500

    rs = RowStore(get_db())
    imported = 0
    errors: list[str] = []
    for row in data_rows:
        values: dict[str, Any] = {}
        for i, col in enumerate(ds["columns"]):
            if i < len(row):
                values[col["key"]] = _coerce_cell(row[i], col["type"])
        try:
            await rs.create_row(ds, values)
            imported += 1
        except (ValueError, KeyError) as exc:
            errors.append(f"row {imported + len(errors) + 1}: {exc}")

    return jsonify({
        "dataset_id": ds["id"],
        "slug": ds["slug"],
        "columns": len(ds["columns"]),
        "imported": imported,
        "errors": errors[:20],
        "total_errors": len(errors),
    }), 201


# ---------------------------------------------------------------------------
# CSV / JSON export
# ---------------------------------------------------------------------------

@bp.get("/datasets/<int:dataset_id>/export")
async def export_dataset(dataset_id: int) -> Any:
    fmt = (request.args.get("format") or "csv").lower()
    store = CatalogStore(get_db())
    ds = await store.get_dataset(dataset_id=dataset_id)
    if not ds:
        return jsonify({"error": "dataset not found"}), 404

    rs = RowStore(get_db())
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        result = await rs.list_rows(ds, page=page, page_size=500)
        items.extend(result["items"])
        if len(items) >= result["total"]:
            break
        page += 1
    col_keys = [c["key"] for c in ds["columns"]]
    col_labels = [c["label"] for c in ds["columns"]]

    if fmt == "json":
        out = {
            "dataset": {"id": ds["id"], "slug": ds["slug"], "name": ds["name"],
                         "description": ds["description"],
                         "columns": [{"key": c["key"], "label": c["label"],
                                      "type": c["type"], "config": c.get("config", {})}
                                     for c in ds["columns"]]},
            "rows": [{k: row.get(k) for k in col_keys} for row in items],
        }
        buf = io.BytesIO(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.seek(0)
        return await send_file(
            buf,
            mimetype="application/json",
            as_attachment=True,
            attachment_filename=f"{ds['slug']}.json",
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(col_labels)
    for row in items:
        writer.writerow([row.get(k, "") for k in col_keys])
    data = buf.getvalue().encode("utf-8")
    out = io.BytesIO(data)
    out.seek(0)
    return await send_file(
        out,
        mimetype="text/csv",
        as_attachment=True,
            attachment_filename=f"{ds['slug']}.csv",
        )


# ---------------------------------------------------------------------------
# Database backup
# ---------------------------------------------------------------------------

@bp.get("/backup")
async def backup_database() -> Any:
    cfg = current_app.config["STATDB"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    download_name = f"statdb-backup-{ts}.db"
    # Use VACUUM INTO for a clean, consistent copy (includes WAL pages)
    backup_path = cfg.data_dir / f"_backup_{ts}.db"
    import sqlite3, asyncio
    def _do_backup(src, dst):
        conn = sqlite3.connect(str(src), isolation_level=None)
        try:
            conn.execute(f"VACUUM INTO '{dst}'")
        finally:
            conn.close()
    await asyncio.to_thread(_do_backup, cfg.db_path, backup_path)
    return await send_file(
        backup_path,
        mimetype="application/octet-stream",
        as_attachment=True,
        attachment_filename=download_name,
    )


# ---------------------------------------------------------------------------
# Views export / import
# ---------------------------------------------------------------------------

@bp.get("/views/export")
async def export_views() -> Any:
    store = ViewStore(get_db())
    views = await store.list_views()
    out = []
    for v in views:
        v["widgets"] = await store.list_widgets(v["id"])
        out.append({
            "name": v["name"],
            "icon": v.get("icon", ""),
            "theme": v.get("theme", ""),
            "settings": v.get("settings", {}),
            "position": v.get("position", 0),
            "widgets": [
                {
                    "type": w["type"],
                    "title": w.get("title", ""),
                    "config": w.get("config", {}),
                    "x": w.get("x", 0),
                    "y": w.get("y", 0),
                    "w": w.get("w", 6),
                    "h": w.get("h", 4),
                    "position": w.get("position", 0),
                }
                for w in v["widgets"]
            ],
        })
    buf = io.BytesIO(
        json.dumps({"version": 1, "views": out}, ensure_ascii=False, indent=2).encode("utf-8")
    )
    buf.seek(0)
    return await send_file(
        buf,
        mimetype="application/json",
        as_attachment=True,
        attachment_filename="statdb-views.json",
    )


@bp.post("/views/import")
async def import_views() -> Any:
    data = await request.get_json(silent=True)
    if not data or not isinstance(data, dict) or not isinstance(data.get("views"), list):
        # try file upload
        files = await request.files
        upload = files.get("file")
        if upload:
            raw = upload.read().decode("utf-8-sig", errors="replace")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                return jsonify({"error": f"invalid JSON: {exc}"}), 400
    if not data or not isinstance(data.get("views"), list):
        return jsonify({"error": "expected JSON body with 'views' array"}), 400

    store = ViewStore(get_db())
    imported = 0
    widgets_added = 0
    errors: list[str] = []
    for item in data["views"]:
        if not isinstance(item, dict) or not item.get("name"):
            errors.append("view missing name")
            continue
        try:
            view = await store.create_view(
                item["name"],
                icon=item.get("icon", ""),
                theme=item.get("theme", ""),
                settings=item.get("settings") or {},
                position=item.get("position", 0),
            )
        except (ValueError, KeyError) as exc:
            errors.append(f"view '{item.get('name')}': {exc}")
            continue
        for w in item.get("widgets", []):
            if not isinstance(w, dict):
                continue
            try:
                await store.add_widget(
                    view["id"],
                    w.get("type", "note"),
                    title=w.get("title", ""),
                    config=w.get("config") or {},
                    geometry={"x": w.get("x", 0), "y": w.get("y", 0),
                              "w": w.get("w", 6), "h": w.get("h", 4),
                              "position": w.get("position", 0)},
                )
                widgets_added += 1
            except (ValueError, KeyError) as exc:
                errors.append(f"widget in '{item['name']}': {exc}")
        imported += 1

    return jsonify({
        "imported_views": imported,
        "imported_widgets": widgets_added,
        "errors": errors[:20],
        "total_errors": len(errors),
    }), 201


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

@bp.get("/snapshots")
async def list_snapshots() -> Any:
    from ..snapshots import list_snapshot_files
    return jsonify({"snapshots": list_snapshot_files()})


@bp.post("/snapshots/trigger")
async def trigger_snapshot() -> Any:
    from ..snapshots import create_snapshot
    info = await create_snapshot()
    if info is None:
        return jsonify({"error": "snapshots disabled"}), 400
    return jsonify(info), 201


@bp.delete("/snapshots/<path:name>")
async def delete_snapshot(name: str) -> Any:
    from ..snapshots import delete_snapshot_file
    ok = delete_snapshot_file(name)
    if not ok:
        return jsonify({"error": "snapshot not found"}), 404
    return jsonify({"deleted": name})
