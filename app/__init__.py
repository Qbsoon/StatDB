"""StatDB — universal, self-hosted data logging & reporting dashboards."""

from __future__ import annotations

import logging

from quart import Quart

from .config import Config

__version__ = "0.1.0"


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )


def create_app(config: Config | None = None) -> Quart:
    """Application factory used both by the dev runner and Hypercorn/Uvicorn."""
    cfg = config or Config()

    _setup_logging(cfg.debug)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    app = Quart(__name__)
    app.config.update(SECRET_KEY=cfg.secret_key, STATDB=cfg)
    app.jinja_env.globals.update(app_name="StatDB", statdb_version=__version__)

    from .api import bp as api_bp
    from .web import bp as web_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    from .auth import register_auth
    register_auth(app)

    from . import db as db_module

    db_module.init_app(app)

    from .snapshots import start_snapshot_scheduler

    @app.before_serving
    async def _start_snapshots() -> None:
        start_snapshot_scheduler(app)

    app.logger.info(
        "StatDB %s initialised — language=%s (default), auth=%s, data_dir=%s",
        __version__,
        cfg.language,
        "password" if cfg.password else "trusted/no-password",
        cfg.data_dir,
    )
    return app
