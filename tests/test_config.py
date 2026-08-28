"""Config unit tests — every test passes a hermetic environ dict."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Config


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keep default data_dir inside tmp
    cfg = Config({})
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 5000
    assert cfg.debug is False
    assert cfg.language == "en"
    assert cfg.language_forced is False
    assert cfg.password is None  # trusted mode by default
    assert cfg.secret_key  # randomly generated
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.db_path == tmp_path / "data" / "statdb.db"


def test_custom_values(tmp_path):
    cfg = Config(
        {
            "STATDB_HOST": "127.0.0.1",
            "STATDB_PORT": "8080",
            "STATDB_DEBUG": "true",
            "STATDB_LANGUAGE": "PL",  # case-insensitive
            "STATDB_PASSWORD": "s3cret",
            "STATDB_SECRET_KEY": "fixed",
            "STATDB_DATA_DIR": str(tmp_path / "storage"),
        }
    )
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8080
    assert cfg.debug is True
    assert cfg.language == "pl"
    assert cfg.language_forced is True
    assert cfg.password == "s3cret"
    assert cfg.secret_key == "fixed"
    assert cfg.db_path == tmp_path / "storage" / "statdb.db"


def test_invalid_language_falls_back_to_en():
    cfg = Config({"STATDB_LANGUAGE": "klingon"})
    assert cfg.language == "en"
    assert cfg.language_forced is False  # invalid value does not force anything


def test_invalid_port_rejected():
    with pytest.raises(ValueError):
        Config({"STATDB_PORT": "not-a-number"})
    with pytest.raises(ValueError):
        Config({"STATDB_PORT": "70000"})


def test_custom_db_path():
    cfg = Config({"STATDB_DB_PATH": "/tmp/elsewhere.db"})
    assert cfg.db_path == Path("/tmp/elsewhere.db")
