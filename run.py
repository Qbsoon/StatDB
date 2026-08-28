"""Development entry point: ``python run.py``.

Production/Docker will use ``hypercorn app:app --bind ...`` instead (F12).
"""

from __future__ import annotations

import asyncio

from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig

from app import create_app

app = create_app()

if __name__ == "__main__":
    cfg = app.config["STATDB"]
    hypercorn_cfg = HyperConfig()
    hypercorn_cfg.bind = [f"{cfg.host}:{cfg.port}"]
    if cfg.debug:
        hypercorn_cfg.use_reloader = True
        hypercorn_cfg.accesslog = "-"
    asyncio.run(serve(app, hypercorn_cfg))
