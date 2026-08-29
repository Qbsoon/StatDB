"""Runtime configuration, loaded from environment variables.

All settings use the ``STATDB_`` prefix. Sensible defaults keep the app
runnable with zero configuration (trusted mode, no password, English UI).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Mapping

DEFAULT_PORT = 5000
SUPPORTED_LANGUAGES = ("en", "pl")
_FALLBACK_LANGUAGE = "en"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def _as_port(value: str | None) -> int:
    if not value:
        return DEFAULT_PORT
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"STATDB_PORT must be an integer, got {value!r}") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"STATDB_PORT out of range (1-65535): {port}")
    return port


class Config:
    """Immutable-ish snapshot of environment-driven settings."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        env = os.environ if environ is None else environ

        self.host = env.get("STATDB_HOST", "0.0.0.0")
        self.port = _as_port(env.get("STATDB_PORT"))
        self.debug = _as_bool(env.get("STATDB_DEBUG"))

        # Language: STATDB_LANGUAGE sets the *default*; the user can always
        # override it via the language toggle (cookie). It is never forced.
        lang_raw = (env.get("STATDB_LANGUAGE") or "").strip().lower()
        self.language = lang_raw if lang_raw in SUPPORTED_LANGUAGES else _FALLBACK_LANGUAGE

        # Auth: when unset, the instance runs in trusted mode (no login page).
        password = (env.get("STATDB_PASSWORD") or "").strip()
        self.password = password or None

        # API token: when set, all /api/* requests must carry
        # ``Authorization: Bearer <token>`` (unless using a public read-only link).
        self.api_token = (env.get("STATDB_API_TOKEN") or "").strip() or None

        # Session secret. Random by default — set STATDB_SECRET_KEY to keep
        # sessions valid across restarts once auth (F11) is enabled.
        self.secret_key = env.get("STATDB_SECRET_KEY") or secrets.token_hex(32)

        # Storage: everything lives under data/ (mount this as a Docker volume).
        self.data_dir = Path(env.get("STATDB_DATA_DIR") or Path.cwd() / "data").expanduser()
        db_path = env.get("STATDB_DB_PATH")
        self.db_path = Path(db_path).expanduser() if db_path else self.data_dir / "statdb.db"
