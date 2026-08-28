from __future__ import annotations

import pytest

from app import create_app
from app.config import Config
from app.db import Database, run_migrations


@pytest.fixture
def env(tmp_path):
    """Hermetic env: isolated data dir, forced Polish UI."""
    return {
        "STATDB_DATA_DIR": str(tmp_path / "data"),
        "STATDB_SECRET_KEY": "test-secret",
        "STATDB_LANGUAGE": "pl",
    }


@pytest.fixture
def config(env):
    return Config(env)


@pytest.fixture
async def app(config):
    """Fresh app + fully migrated DB for each test (before_serving doesn't
    fire under Quart's test_client, so we migrate explicitly)."""
    application = create_app(config)
    db = Database(config.db_path)
    await run_migrations(db)
    return application


@pytest.fixture
def client(app):
    """Quart test client — use `await client.get(...)` etc."""
    return app.test_client()
