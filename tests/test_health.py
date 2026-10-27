from datetime import date
from types import SimpleNamespace

import pytest

from app.health import SOURCE, daily_metrics, sync_health, vo2_metrics


def test_daily_means_units_missing_values_and_semantics():
    metrics = daily_metrics("2026-10-20",
        {"totalSteps": 123, "totalDistanceMeters": 2500, "stressDuration": 600,
         "averageStressLevel": -1, "averageSpo2": 0, "activeSeconds": 1200},
        {"heartRateValues": [[1, 60], [2, 90], [3, None], [4, -1], [5, 0]],
         "restingHeartRate": 50, "minHeartRate": 42, "maxHeartRate": 160},
        {"hrvSummary": {"lastNightAvg": 45, "lastNight5MinHigh": 80}},
        {"dailySleepDTO": {"sleepTimeSeconds": 27000, "deepSleepSeconds": 3600,
                           "sleepScores": {"overall": {"value": 75}}}},
        [{"weight": 70000, "muscleMass": 50000, "bodyFat": 20},
         {"weight": 72000, "muscleMass": 52000, "bodyFat": 22},
         {"weight": None, "bodyFat": float("nan")}],
        {"respirationValuesArray": [[1, 12], [2, 16], [3, -1], [4, None]]})
    values = {m["type"]: m["value"] for m in metrics}
    assert values["HR_AVG_DAILY"] == 75
    assert values["RESPIRATION_RATE_AVG"] == 14
    assert values["HR_REST"] == 50 and values["HR_MAX_DAILY"] == 160
    assert values["WEIGHT"] == 71 and values["MUSCLE_MASS"] == 51
    assert values["BODY_FAT"] == 21
    assert values["SLEEP_DURATION"] == 7.5 and values["SLEEP_DEEP_DURATION"] == 1
    assert values["STRESS_DURATION"] == 10 and values["DAILY_DISTANCE"] == 2.5
    assert values["DAILY_STEPS"] == 123 and values["DAILY_ACTIVE_MINUTES"] == 20
    assert values["HRV_LAST_NIGHT_AVG"] == 45 and values["HRV_LAST_NIGHT_5MIN_HIGH"] == 80
    assert "STRESS_AVERAGE" not in values and "PULSE_OX_AVG" not in values
    assert "HR_MAX" not in values and "RMSSD" not in values


class Garmin:
    def get_body_composition(self, start, end):
        return {"dateWeightList": [
            {"calendarDate": "2026-10-19", "weight": 70000},
            {"calendarDate": "2026-10-19", "weight": 72000}]}
    def get_stats(self, day):
        return {"totalSteps": 100}
    def get_heart_rates(self, day):
        return {"heartRateValues": [[0, 60], [1, 80]], "restingHeartRate": 50}
    def get_hrv_data(self, day):
        return None
    def get_sleep_data(self, day):
        return {}
    def get_respiration_data(self, day):
        return {}
    def get_max_metrics(self, day):
        return []


class API:
    def __init__(self):
        self.rows = [{"date": "2026-10-19T00:00:00Z", "type": "HR_REST", "value": 55, "notes": None}]
        self.writes = []
    def metrics(self):
        return self.rows
    def upsert_metric(self, metric):
        self.writes.append(metric)
        self.rows = [r for r in self.rows if (r["date"][:10], r["type"]) != (metric["date"], metric["type"])]
        self.rows.append(metric)
        return metric


def test_backfill_calendar_dates_manual_protection_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setattr("app.health.time.sleep", lambda _: None)
    c = SimpleNamespace(health_lookback_days=2, data_dir=tmp_path)
    g, api = SimpleNamespace(client=Garmin()), API()
    report = sync_health(c, g, api, end=date(2026, 10, 20))
    assert report["start"] == "2026-10-19" and report["end"] == "2026-10-20"
    assert report["preserved_manual"] == 1 and report["failures"] == 0
    assert next(m for m in api.rows if m["type"] == "WEIGHT")["value"] == 71
    assert all(m["date"] == "2026-10-19" for m in api.rows if m["type"] == "WEIGHT")
    count = len(api.writes)
    repeat = sync_health(c, g, api, end=date(2026, 10, 20))
    assert len(api.writes) == count and repeat["written"] == 0
    assert repeat["unchanged"] == count


def test_failed_fetch_does_not_write_zero_and_other_metrics_continue(tmp_path, monkeypatch):
    monkeypatch.setattr("app.health.time.sleep", lambda _: None)
    garmin = Garmin()
    def fail(_):
        raise RuntimeError("Unavailable")
    garmin.get_heart_rates = fail
    api = API()
    with pytest.raises(RuntimeError, match="1 failures"):
        sync_health(SimpleNamespace(health_lookback_days=1, data_dir=tmp_path),
                    SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert all(m["type"] != "HR_AVG_DAILY" for m in api.writes)
    assert any(m["type"] == "DAILY_STEPS" for m in api.writes)
    assert (tmp_path / "health" / "last-report.json").exists()


def test_new_zeros_are_reported_not_sent_to_positive_only_api(tmp_path, monkeypatch):
    monkeypatch.setattr("app.health.time.sleep", lambda _: None)
    garmin, api = Garmin(), API()
    garmin.get_stats = lambda day: {"floorsAscended": 0, "totalSteps": 123}
    report = sync_health(SimpleNamespace(health_lookback_days=1, data_dir=tmp_path),
                         SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert report["zero_not_supported"] == 1
    assert all(m["value"] > 0 for m in api.writes)


def test_vo2_separate_sports_precision_and_measured_date():
    day = "2026-10-20"
    rows = vo2_metrics(day, [{
        "generic": {"calendarDate": day, "vo2MaxValue": 50, "vo2MaxPreciseValue": 50.1234567},
        "cycling": {"calendarDate": day, "vo2MaxValue": 55},
    }, {"generic": {"calendarDate": "2026-10-19", "vo2MaxValue": 60}}])
    assert {r["type"]: r["value"] for r in rows} == {"VO2MAX": 50.123457, "VO2MAX_CYCLING": 55}
    assert all(r["date"] == day and r["notes"].startswith(SOURCE) for r in rows)


@pytest.mark.parametrize("value", [None, True, False, 0, -1, float("nan"), float("inf"), "50"])
def test_vo2_invalid_values_and_rounded_fallback(value):
    record = {"calendarDate": "2026-10-20", "vo2MaxPreciseValue": value, "vo2MaxValue": value}
    assert vo2_metrics("2026-10-20", [{"generic": record}]) == []
    record["vo2MaxValue"] = 49.5
    assert vo2_metrics("2026-10-20", [{"generic": record}])[0]["value"] == 49.5


@pytest.mark.parametrize("response", [None, {}, [], [{"generic": None, "cycling": None}],
                                    [{"generic": {"vo2MaxValue": 50}}]])
def test_vo2_missing_data_does_not_invent_measurements(response):
    assert vo2_metrics("2026-10-20", response) == []


@pytest.mark.parametrize("response", [{"unexpected": 1}, "bad", [None], [{"generic": []}]])
def test_vo2_unexpected_response_is_reported(response):
    with pytest.raises(ValueError, match="Unexpected Garmin"):
        vo2_metrics("2026-10-20", response)


def test_vo2_sync_manual_protection_updates_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setattr("app.health.time.sleep", lambda _: None)
    c = SimpleNamespace(health_lookback_days=1, data_dir=tmp_path)
    garmin, api = Garmin(), API()
    day = "2026-10-20"
    garmin.get_max_metrics = lambda requested: [{
        "generic": {"calendarDate": requested, "vo2MaxPreciseValue": 51.23},
        "cycling": {"calendarDate": requested, "vo2MaxValue": 55},
    }]
    api.rows.extend([
        {"date": day, "type": "VO2MAX", "value": 50, "notes": SOURCE},
        {"date": day, "type": "VO2MAX_CYCLING", "value": 54, "notes": "Manual"},
    ])
    report = sync_health(c, SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert report["failures"] == 0 and report["preserved_manual"] == 1
    assert report["types"]["VO2MAX"] == 1
    assert next(r for r in api.rows if r["type"] == "VO2MAX")["value"] == 51.23
    assert next(r for r in api.rows if r["type"] == "VO2MAX_CYCLING")["value"] == 54
    count = len(api.writes)
    report = sync_health(c, SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert len(api.writes) == count and report["written"] == 0


def test_vo2_creates_both_sports_on_their_measured_days(tmp_path, monkeypatch):
    monkeypatch.setattr("app.health.time.sleep", lambda _: None)
    garmin, api = Garmin(), API()
    requested = []
    def fetch(day):
        requested.append(day)
        if day == "2026-10-19":
            return [{"generic": {"calendarDate": day, "vo2MaxValue": 50},
                     "cycling": {"calendarDate": day, "vo2MaxPreciseValue": 55.123}}]
        # A stale estimate must not be copied to the next day.
        return [{"generic": {"calendarDate": "2026-10-19", "vo2MaxValue": 50}}]
    garmin.get_max_metrics = fetch
    c = SimpleNamespace(health_lookback_days=2, data_dir=tmp_path)
    report = sync_health(c, SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert requested == ["2026-10-19", "2026-10-20"]
    rows = [r for r in api.writes if r["type"].startswith("VO2MAX")]
    assert {r["type"]: r["value"] for r in rows} == {"VO2MAX": 50, "VO2MAX_CYCLING": 55.123}
    assert all(r["date"] == "2026-10-19" for r in rows)
    assert report["types"]["VO2MAX"] == report["types"]["VO2MAX_CYCLING"] == 1
    count = len(api.writes)
    repeat = sync_health(c, SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert len(api.writes) == count and repeat["written"] == 0


@pytest.mark.parametrize("malformed", [False, True])
def test_vo2_failure_preserves_existing_and_continues_other_metrics(tmp_path, monkeypatch, malformed):
    monkeypatch.setattr("app.health.time.sleep", lambda _: None)
    garmin, api = Garmin(), API()
    def fetch(day):
        if malformed:
            return [{"cycling": "invalid"}]
        raise RuntimeError("Unavailable")
    garmin.get_max_metrics = fetch
    old = {"date": "2026-10-20", "type": "VO2MAX", "value": 50, "notes": SOURCE}
    api.rows.append(old.copy())
    with pytest.raises(RuntimeError, match="1 failures"):
        sync_health(SimpleNamespace(health_lookback_days=1, data_dir=tmp_path),
                    SimpleNamespace(client=garmin), api, end=date(2026, 10, 20))
    assert old in api.rows
    assert not any(r["type"].startswith("VO2MAX") for r in api.writes)
    assert any(r["type"] == "DAILY_STEPS" for r in api.writes)
