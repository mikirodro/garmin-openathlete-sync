import pytest
from app.config import Config


def environment(monkeypatch, tmp_path):
    for key in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "OPENATHLETE_EMAIL", "OPENATHLETE_PASSWORD"):
        monkeypatch.setenv(key, "test")
        monkeypatch.delenv(key + "_FILE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SYNC_INTERVAL_SECONDS", raising=False)


def test_daily_default(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    assert Config.from_env().sync_interval == 86400


def test_invalid_interval(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    monkeypatch.setenv("SYNC_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError):
        Config.from_env()
