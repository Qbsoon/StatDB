"""HTML pages blueprint."""

from __future__ import annotations

import json

from quart import (
    Blueprint,
    abort,
    current_app,
    g,
    make_response,
    redirect,
    render_template,
    request,
)

from typing import Any

from ..catalog.store import CatalogStore
from ..db import get_db
from ..i18n import COOKIE_NAME, SUPPORTED, make_translator, resolve_language
from ..rows.store import RowStore
from ..views.store import ViewStore, WIDGET_TYPES

bp = Blueprint("web", __name__)

_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


@bp.before_app_request
async def pick_language() -> None:
    cfg = current_app.config["STATDB"]
    g.lang = resolve_language(
        default_language=cfg.language,
        cookie_language=request.cookies.get(COOKIE_NAME),
    )
    g.t = make_translator(g.lang)


@bp.app_context_processor
def inject_template_helpers() -> dict:
    cfg = current_app.config["STATDB"]
    return {
        "lang": g.get("lang", "en"),
        "t": g.get("t", make_translator("en")),
        "g": g,
        "statdb_has_password": bool(cfg.password),
    }


@bp.route("/")
async def index():
    return await render_template("index.html")


@bp.route("/public/views/<int:vid>")
async def public_view(vid: int):
    """Read-only public view — bypasses auth entirely."""
    store = ViewStore(get_db())
    view = await store.get_view(vid)
    if not view:
        abort(404)
    view["widgets"] = await store.list_widgets(vid)
    return await render_template("public_view.html", view=view)


@bp.route("/views")
async def views():
    store = ViewStore(get_db())
    items = await store.list_views()
    for v in items:
        v["widgets"] = await store.list_widgets(v["id"])
    return await render_template("views.html", views=items)


@bp.route("/views/<int:view_id>")
async def view_detail(view_id: int):
    store = ViewStore(get_db())
    view = await store.get_view(view_id)
    if not view:
        abort(404)
    view["widgets"] = await store.list_widgets(view_id)
    datasets = await CatalogStore(get_db()).list_datasets()
    return await render_template(
        "view_detail.html",
        view=view,
        datasets=datasets,
        widget_types=sorted(WIDGET_TYPES),
    )


@bp.route("/views", methods=["POST"])
async def view_create():
    form = await request.form
    store = ViewStore(get_db())
    view = await store.create_view(
        name=str(form.get("name", "")),
    )
    return redirect(f"/views/{view['id']}")


# ---------- widgets (F8) ----------

async def _views_ctx(view_id: int) -> tuple[ViewStore, dict[str, Any]]:
    store = ViewStore(get_db())
    view = await store.get_view(view_id)
    if not view:
        abort(404)
    return store, view


@bp.route("/views/<int:view_id>/widgets", methods=["POST"])
async def widget_create(view_id: int):
    store, view = await _views_ctx(view_id)
    form = await request.form
    widget_type = str(form.get("type", "")).strip()
    title = str(form.get("title", ""))
    dataset_id = form.get("dataset_id")
    config: dict[str, Any] = {}
    if dataset_id:
        config["dataset_id"] = int(dataset_id)
    column_name = str(form.get("column", "")).strip()
    if column_name:
        config["column"] = column_name
    await store.add_widget(view["id"], widget_type, title=title, config=config)
    return redirect(f"/views/{view_id}")


@bp.route("/views/<int:view_id>/layout", methods=["POST"])
async def views_layout_save(view_id: int):
    store, view = await _views_ctx(view_id)
    payload = await request.get_json(silent=True)
    if not isinstance(payload, list):
        abort(400)
    try:
        await store.set_layout(view["id"], payload)
    except (KeyError, ValueError):
        abort(400)
    return {"ok": True}


@bp.route("/views/<int:view_id>/widgets/<int:widget_id>", methods=["POST"])
async def widget_update(view_id: int, widget_id: int):
    store, view = await _views_ctx(view_id)
    form = await request.form
    widget = await store.get_widget(widget_id)
    if not widget or widget.get("view_id") != view["id"]:
        abort(404)
    title = str(form.get("title", "")).strip()
    try:
        config = json.loads(str(form.get("config", "") or "{}") or "{}")
        if not isinstance(config, dict):
            config = {}
    except json.JSONDecodeError:
        config = {}
    await store.update_widget(widget["id"], title=title, config=config)
    return redirect(f"/views/{view_id}")


@bp.route("/views/<int:view_id>/widgets/<int:widget_id>/delete", methods=["POST"])
async def widget_delete(view_id: int, widget_id: int):
    store, view = await _views_ctx(view_id)
    widget = await store.get_widget(widget_id)
    if widget and widget.get("view_id") == view["id"]:
        try:
            await store.delete_widget(widget_id)
        except KeyError:
            abort(404)
    return redirect(f"/views/{view_id}")


@bp.route("/views/<int:view_id>/settings", methods=["POST"])
async def view_settings_save(view_id: int):
    store, view = await _views_ctx(view_id)
    form = await request.form
    settings = dict(view.get("settings") or {})
    settings["custom_css"] = str(form.get("custom_css", ""))
    try:
        settings["refresh"] = max(0, int(form.get("refresh", 0)))
    except (ValueError, TypeError):
        settings["refresh"] = 0
    settings["kiosk"] = form.get("kiosk") == "1"
    await store.update_view(view["id"], settings=settings)
    return redirect(f"/views/{view_id}")


@bp.route("/datasets")
async def datasets():
    store = CatalogStore(get_db())
    items = await store.list_datasets()
    return await render_template("datasets.html", datasets=items)


@bp.route("/datasets/<int:dataset_id>")
async def dataset_detail(dataset_id: int):
    db = get_db()
    ds = await CatalogStore(db).get_dataset(dataset_id=dataset_id)
    if not ds:
        abort(404)
    rows = await RowStore(db).list_rows(ds, page=1, page_size=500)
    return await render_template("dataset.html", dataset=ds, rows=rows)


# ---------- dataset forms (F6) ----------


def _safe_next(default: str = "/datasets") -> str:
    target = request.args.get("next") or default
    return target if target.startswith("/") else default


async def _form_catalog() -> tuple[CatalogStore, dict]:
    form = await request.form
    return CatalogStore(get_db()), form


@bp.post("/datasets")
async def dataset_create():
    store, form = await _form_catalog()
    slug = str(form.get("slug", "")).strip().lower()
    name = str(form.get("name", "")).strip()
    description = str(form.get("description", "")).strip()
    try:
        ds = await store.create_dataset(slug, name, description)
    except (ValueError, KeyError):
        return redirect("/datasets")  # invalid slug / duplicate — list stays source of truth
    return redirect(f"/datasets/{ds['id']}")


@bp.post("/datasets/presets/months")
async def dataset_months_preset():
    store, _ = await _form_catalog()
    ds = await store.create_months_preset()
    return redirect(f"/datasets/{ds['id']}")


@bp.post("/datasets/<int:dataset_id>/columns")
async def column_add(dataset_id: int):
    store, form = await _form_catalog()
    try:
        config = json.loads(str(form.get("config", "{}")) or "{}")
        if not isinstance(config, dict):
            config = {}
    except ValueError:
        config = {}
    try:
        await store.add_column(
            dataset_id,
            key=str(form.get("key", "")),
            label=str(form.get("label", "")) or str(form.get("key", "")),
            type_key=str(form.get("type", "text")),
            config=config,
        )
    except (ValueError, KeyError):
        pass  # invalid key/type/duplicate — stay on page
    return redirect(_safe_next(f"/datasets/{dataset_id}"))


@bp.post("/datasets/<int:dataset_id>/columns/preset-month")
async def column_month_preset(dataset_id: int):
    """Add a ready-made year-month 'month' column (MM-YYYY) if missing."""
    store, _ = await _form_catalog()
    ds = await store.get_dataset(dataset_id=dataset_id)
    if not ds:
        abort(404)
    if not any(c["key"] == "month" for c in ds["columns"]):
        label = "Miesiąc" if g.get("lang", "en") == "pl" else "Month"
        await store.add_column(
            dataset_id,
            key="month",
            label=label,
            type_key="year-month",
            config={"input_format": "MM-YYYY"},
        )
    return redirect(_safe_next(f"/datasets/{dataset_id}"))


@bp.post("/columns/<int:column_id>/update")
async def column_update(column_id: int):
    store, form = await _form_catalog()
    try:
        config = json.loads(str(form.get("config", "{}")) or "{}")
        if not isinstance(config, dict):
            config = None
    except ValueError:
        config = None
    try:
        await store.update_column(column_id, label=str(form.get("label", "")) or None, config=config)
    except KeyError:
        abort(404)
    return redirect(_safe_next())


@bp.post("/columns/<int:column_id>/delete")
async def column_delete(column_id: int):
    store, _ = await _form_catalog()
    await store.remove_column(column_id)
    return redirect(_safe_next())


# ---------- record forms (F7) ----------

_BOOL_TRUE = {"1", "true", "on", "yes"}


def _coerce_value(col: dict, raw: str) -> Any:
    """Convert a form string into the Python type the row validator expects."""
    raw = raw.strip()
    if not raw:
        return None
    type_key = col["type"]
    if type_key in ("integer", "year"):
        return int(raw)
    if type_key in ("float", "currency"):
        return float(raw.replace(",", "."))  # allow Polish decimal comma
    return raw


def _row_form_values(columns: list[dict], form) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for col in columns:
        if col["type"] == "formula":
            continue  # computed server-side, not editable
        if col["type"] == "bool":
            values[col["key"]] = str(form.get(col["key"], "")).lower() in _BOOL_TRUE
        elif col["key"] in form:
            values[col["key"]] = _coerce_value(col, str(form.get(col["key"], "")))
    return values


async def _rows_ctx(dataset_id: int) -> tuple[RowStore, dict, Any]:
    db = get_db()
    ds = await CatalogStore(db).get_dataset(dataset_id=dataset_id)
    if not ds:
        abort(404)
    return RowStore(db), ds, await request.form


@bp.post("/datasets/<int:dataset_id>/rows")
async def row_create(dataset_id: int):
    store, ds, form = await _rows_ctx(dataset_id)
    try:
        await store.create_row(ds, _row_form_values(ds["columns"], form))
    except ValueError:
        pass  # invalid value — stay on page, table remains source of truth
    return redirect(_safe_next(f"/datasets/{dataset_id}"))


@bp.post("/datasets/<int:dataset_id>/rows/<int:row_id>")
async def row_update(dataset_id: int, row_id: int):
    store, ds, form = await _rows_ctx(dataset_id)
    try:
        await store.update_row(ds, row_id, _row_form_values(ds["columns"], form))
    except KeyError:
        abort(404)
    except ValueError:
        pass
    return redirect(_safe_next(f"/datasets/{dataset_id}"))


@bp.post("/datasets/<int:dataset_id>/rows/<int:row_id>/delete")
async def row_delete(dataset_id: int, row_id: int):
    store, ds, _ = await _rows_ctx(dataset_id)
    await store.delete_row(ds, row_id)
    return redirect(_safe_next(f"/datasets/{dataset_id}"))


@bp.route("/lang/<lang>")
async def set_language_cookie(lang: str):
    """Toggle UI language (EN/PL). The cookie overrides the STATDB_LANGUAGE default."""
    target = request.args.get("next") or "/"
    if not target.startswith("/"):
        target = "/"
    resp = await make_response(redirect(target))
    if lang in SUPPORTED:
        resp.set_cookie(COOKIE_NAME, lang, max_age=_COOKIE_MAX_AGE, samesite="Lax")
    return resp


# ---------- F10: import / export / backup / transfer ----------

import csv as csv_mod
import io as io_mod
from pathlib import Path as _Path
from quart import send_file, jsonify as _jsonify


@bp.post("/datasets/import-csv")
async def dataset_import_csv():
    """Upload a CSV file → create dataset with inferred columns + rows."""
    from ..api.transfer import _infer_type, _coerce_cell
    files = await request.files
    form = await request.form
    upload = files.get("file")
    if not upload or not upload.filename:
        return redirect("/datasets")
    raw = upload.read().decode("utf-8-sig", errors="replace")
    reader = csv_mod.reader(io_mod.StringIO(raw))
    try:
        header = next(reader)
    except StopIteration:
        return redirect("/datasets")
    header = [h.strip() for h in header]
    data_rows = list(reader)
    if not header:
        return redirect("/datasets")

    import re as _re
    def _safe_key(h: str) -> str:
        k = "".join(c if c.isalnum() or c == "_" else "_" for c in h.lower()).strip("_")
        if k and k[0].isdigit():
            k = "col_" + k
        return k or "col"

    keys = [_safe_key(h) for h in header]
    seen: dict[str, int] = {}
    for i, k in enumerate(keys):
        if k in seen:
            seen[k] += 1
            keys[i] = f"{k}_{seen[k]}"
        else:
            seen[k] = 1

    col_samples: list[list[str]] = [[] for _ in header]
    for row in data_rows[:200]:
        for i, cell in enumerate(row[: len(header)]):
            if cell.strip():
                col_samples[i].append(cell)
    from ..api.transfer import _infer_type
    types = [_infer_type(s) for s in col_samples]

    slug = (form.get("slug") or "").strip().lower()
    name = (form.get("name") or "").strip()
    if not slug:
        base = _Path(upload.filename).stem
        slug = "".join(c if c.isalnum() or c == "_" else "_" for c in base.lower()).strip("_")
        if slug and slug[0].isdigit():
            slug = "ds_" + slug
    if not name:
        name = _Path(upload.filename).stem.replace("_", " ").title() or slug

    store = CatalogStore(get_db())
    try:
        ds = await store.create_dataset(slug, name)
    except (ValueError, KeyError):
        return redirect("/datasets")

    for pos, (key, ty) in enumerate(zip(keys, types), 1):
        label = header[pos - 1] or key
        config: dict[str, Any] = {}
        if ty == "year-month":
            config["input_format"] = "MM-YYYY"
        try:
            await store.add_column(ds["id"], key, label, ty, config, pos)
        except (ValueError, KeyError):
            continue

    ds = await store.get_dataset(dataset_id=ds["id"])
    if not ds:
        return redirect("/datasets")

    from ..api.transfer import _coerce_cell
    rs = RowStore(get_db())
    for row in data_rows:
        values: dict[str, Any] = {}
        for i, col in enumerate(ds["columns"]):
            if i < len(row):
                values[col["key"]] = _coerce_cell(row[i], col["type"])
        try:
            await rs.create_row(ds, values)
        except (ValueError, KeyError):
            pass
    return redirect(f"/datasets/{ds['id']}")


@bp.route("/datasets/<int:dataset_id>/export")
async def dataset_export(dataset_id: int):
    """Download dataset as CSV or JSON (?format=csv|json)."""
    fmt = (request.args.get("format") or "csv").lower()
    store = CatalogStore(get_db())
    ds = await store.get_dataset(dataset_id=dataset_id)
    if not ds:
        abort(404)
    rs = RowStore(get_db())
    all_rows = []
    page = 1
    while True:
        result = await rs.list_rows(ds, page=page, page_size=500)
        all_rows.extend(result["items"])
        if len(all_rows) >= result["total"]:
            break
        page += 1
    items = all_rows
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
        buf = io_mod.BytesIO(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"))
        buf.seek(0)
        return await send_file(buf, mimetype="application/json", as_attachment=True,
                                 attachment_filename=f"{ds['slug']}.json")

    buf = io_mod.StringIO()
    writer = csv_mod.writer(buf)
    writer.writerow(col_labels)
    for row in items:
        writer.writerow([row.get(k, "") for k in col_keys])
    data = buf.getvalue().encode("utf-8")
    out = io_mod.BytesIO(data)
    out.seek(0)
    return await send_file(out, mimetype="text/csv", as_attachment=True,
                             attachment_filename=f"{ds['slug']}.csv")


@bp.route("/backup")
async def backup_download():
    """Download a copy of the SQLite database."""
    from datetime import datetime, timezone
    import sqlite3, asyncio
    cfg = current_app.config["STATDB"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = cfg.data_dir / f"_backup_{ts}.db"

    def _do_backup(src, dst):
        conn = sqlite3.connect(str(src), isolation_level=None)
        try:
            conn.execute(f"VACUUM INTO '{dst}'")
        finally:
            conn.close()

    await asyncio.to_thread(_do_backup, cfg.db_path, backup_path)
    buf = io_mod.BytesIO(backup_path.read_bytes())
    buf.seek(0)
    backup_path.unlink(missing_ok=True)
    return await send_file(buf, mimetype="application/octet-stream",
                             as_attachment=True, attachment_filename=f"statdb-backup-{ts}.db")


@bp.route("/transfer")
async def transfer_page():
    """Settings page: import/export views config, snapshots, backup link."""
    from ..snapshots import list_snapshot_files, _is_enabled
    cfg = current_app.config["STATDB"]
    snapshots = list_snapshot_files(cfg)
    snap_enabled = _is_enabled(cfg)
    return await render_template(
        "transfer.html",
        snapshots=snapshots,
        snap_enabled=snap_enabled,
    )


@bp.post("/transfer/views-import")
async def views_import_web():
    """Import views config from uploaded JSON file."""
    files = await request.files
    upload = files.get("file")
    if not upload:
        return redirect("/transfer")
    import json as _json
    raw = upload.read().decode("utf-8-sig", errors="replace")
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        return redirect("/transfer")
    if not isinstance(data, dict) or not isinstance(data.get("views"), list):
        return redirect("/transfer")

    store = ViewStore(get_db())
    for item in data["views"]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        try:
            view = await store.create_view(
                item["name"],
                icon=item.get("icon", ""),
                theme=item.get("theme", ""),
                settings=item.get("settings") or {},
                position=item.get("position", 0),
            )
        except (ValueError, KeyError):
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
            except (ValueError, KeyError):
                pass
    return redirect("/views")


@bp.post("/transfer/snapshots/trigger")
async def snapshot_trigger_web():
    from ..snapshots import create_snapshot
    await create_snapshot()
    return redirect("/transfer")


@bp.post("/transfer/snapshots/<path:name>/delete")
async def snapshot_delete_web(name: str):
    from ..snapshots import delete_snapshot_file
    delete_snapshot_file(name)
    return redirect("/transfer")
