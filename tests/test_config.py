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


def test_health_window(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    monkeypatch.setenv("GARMIN_HEALTH_LOOKBACK_DAYS", "30")
    assert Config.from_env().health_lookback_days == 30
    monkeypatch.setenv("GARMIN_HEALTH_LOOKBACK_DAYS", "0")
    with pytest.raises(ValueError):
        Config.from_env()


def test_planned_horizon_bounds(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    monkeypatch.setenv("GARMIN_PLANNED_DAYS", "90")
    assert Config.from_env().planned_days == 90
    monkeypatch.setenv("GARMIN_PLANNED_DAYS", "367")
    with pytest.raises(ValueError):
        Config.from_env()
