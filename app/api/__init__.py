"""REST API blueprint. Mounted at /api. Sub-routers land per phase."""

from __future__ import annotations

from quart import Blueprint, jsonify, request

from ..auth import check_api_auth
from ..db import get_db

bp = Blueprint("api", __name__, url_prefix="/api")

# Sub-routers land here as blueprints (no extra prefix) so they inherit /api.
from . import aggregate as aggregate_bp
from . import datasets as datasets_bp
from . import rows as rows_bp
from . import transfer as transfer_bp
from . import views as views_bp

bp.register_blueprint(datasets_bp.bp)
bp.register_blueprint(rows_bp.bp)
bp.register_blueprint(aggregate_bp.bp)
bp.register_blueprint(views_bp.bp)
bp.register_blueprint(transfer_bp.bp)


@bp.before_request
async def _api_auth_gate() -> tuple | None:
    """Require bearer token or session for all /api/* routes (except healthz)."""
    if request.path == "/api/healthz":
        return None
    if not check_api_auth():
        return jsonify({"error": "authentication required"}), 401
    return None


@bp.get("/healthz")
async def healthz():
    """Liveness + DB reachability probe (Docker/compose healthcheck target)."""
    db = get_db()
    try:
        await db.quick_check()
    except Exception as exc:  # pragma: no cover - defensive, tested via monkeypatch
        return jsonify(status="error", db=str(exc)), 503
    return jsonify(status="ok", db="ok"), 200
