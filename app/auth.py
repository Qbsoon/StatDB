"""F11 — Authentication: optional password (env), API token, public read-only links.

Auth model:
  * No password set → trusted mode (everything open).
  * Password set → web UI requires login (session cookie). API requires
    either a valid session OR ``Authorization: Bearer <api_token>``.
  * API token set (``STATDB_API_TOKEN``) → all /api/* must carry the bearer
    token (independent of password).
  * Public read-only links: ``/public/views/<id>`` bypass auth entirely,
    rendering a single view + its widgets in read-only mode.
"""

from __future__ import annotations

import hmac
from typing import Any

from quart import (
    Blueprint,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
)

bp = Blueprint("auth", __name__)

_SESSION_KEY = "statdb_authed"
_LOGIN_PATH = "/login"
_LOGOUT_PATH = "/logout"

# Paths that never require auth.
_PUBLIC_PREFIXES = (
    "/public",
    "/login",
    "/logout",
    "/api/healthz",
    "/static",
)


def _cfg() -> Any:
    return current_app.config["STATDB"]


def is_authed() -> bool:
    """True when the current session is authenticated (or no password set)."""
    cfg = _cfg()
    if not cfg.password:
        return True
    return bool(session.get(_SESSION_KEY))


def check_api_auth() -> bool:
    """True when the API request is authorised (session or bearer token)."""
    cfg = _cfg()
    # No password and no token → open API.
    if not cfg.password and not cfg.api_token:
        return True
    # Bearer token check.
    if cfg.api_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if hmac.compare_digest(token, cfg.api_token):
                return True
    # Session check (browser same-origin).
    if cfg.password and is_authed():
        return True
    return False


@bp.before_app_request
async def gatekeep() -> Any:
    """Global gate: redirect to login if password is set and not authed."""
    cfg = _cfg()
    if not cfg.password:
        return None
    path = request.path
    # Public paths bypass auth.
    for pfx in _PUBLIC_PREFIXES:
        if path == pfx or path.startswith(pfx + "/") or path == pfx.rstrip("/"):
            return None
    if is_authed():
        return None
    # API requests get 401 JSON instead of redirect.
    if path.startswith("/api/"):
        from quart import jsonify
        return jsonify({"error": "authentication required"}), 401
    return redirect(f"{_LOGIN_PATH}?next={path}")


@bp.route("/login", methods=["GET", "POST"])
async def login_page() -> Any:
    cfg = _cfg()
    if not cfg.password:
        return redirect("/")
    if request.method == "POST":
        form = await request.form
        password = form.get("password", "")
        if hmac.compare_digest(password, cfg.password):
            session[_SESSION_KEY] = True
            nxt = (form.get("next") or "/").strip()
            # prevent open redirect
            if not nxt.startswith("/"):
                nxt = "/"
            return redirect(nxt)
        from .i18n import make_translator, resolve_language, COOKIE_NAME
        cfg2 = _cfg()
        lang = resolve_language(
            forced=cfg2.language_forced,
            env_language=cfg2.language,
            cookie_language=request.cookies.get(COOKIE_NAME),
        )
        g.lang = lang
        g.t = make_translator(lang)
        return await render_template("login.html", error=True), 401
    from .i18n import make_translator, resolve_language, COOKIE_NAME
    cfg3 = _cfg()
    lang = resolve_language(
        forced=cfg3.language_forced,
        env_language=cfg3.language,
        cookie_language=request.cookies.get(COOKIE_NAME),
    )
    g.lang = lang
    g.t = make_translator(lang)
    nxt = request.args.get("next", "/")
    return await render_template("login.html", error=False, next_path=nxt)


@bp.route("/logout", methods=["POST", "GET"])
async def logout() -> Any:
    session.pop(_SESSION_KEY, None)
    return redirect("/login")


def register_auth(app: Any) -> None:
    """Attach the auth blueprint + before_request gatekeep."""
    from .i18n import make_translator

    app.config["_fallback_t"] = make_translator("en")
    app.register_blueprint(bp)
