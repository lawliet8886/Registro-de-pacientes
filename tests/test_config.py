import json
from datetime import datetime as real_datetime

import pytest

pytest.importorskip("pandas")
pytest.importorskip("PyQt5")

import registro_pac


def test_load_cfg_missing_file(tmp_path, monkeypatch):
    cfg_path = tmp_path / "settings.json"
    monkeypatch.setattr(registro_pac, "CONFIG_FILE", cfg_path)

    assert registro_pac._load_cfg() == {}


def test_load_cfg_invalid_json_returns_empty(tmp_path, monkeypatch):
    cfg_path = tmp_path / "settings.json"
    cfg_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(registro_pac, "CONFIG_FILE", cfg_path)

    assert registro_pac._load_cfg() == {}


def test_save_cfg_writes_pretty_json(tmp_path, monkeypatch):
    cfg_path = tmp_path / "settings.json"
    monkeypatch.setattr(registro_pac, "CONFIG_FILE", cfg_path)

    data = {"backup_root": "example"}
    registro_pac._save_cfg(data)

    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved == data
    assert "  " in cfg_path.read_text(encoding="utf-8")


def test_backup_now_creates_timestamped_copy(tmp_path, monkeypatch):
    source_db = tmp_path / "patients.db"
    source_db.write_text("database-contents", encoding="utf-8")
    monkeypatch.setattr(registro_pac, "DB_PATH", source_db)

    backup_root = tmp_path / "backup"
    monkeypatch.setattr(registro_pac, "get_backup_root", lambda parent=None: backup_root)

    class FixedDateTime:
        @classmethod
        def now(cls):
            return real_datetime(2024, 1, 2, 3, 4, 5)

    monkeypatch.setattr(registro_pac, "datetime", FixedDateTime)

    registro_pac.backup_now(parent=None)

    expected = backup_root / "2024-01" / "02" / "patients_03-04-05.db"
    assert expected.exists()
    assert expected.read_text(encoding="utf-8") == "database-contents"
