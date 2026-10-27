import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.health import SOURCE
from app.performance import ftp_records, sync_performance


def row(day="2026-10-20", watts=300, sport="CYCLING", **extra):
    return {"from": day, "until": day, "updatedDate": day,
            "series": sport.lower(), "value": watts, **extra}


class Garmin:
    def __init__(self, running=(), cycling=(), weights=()):
        self.data = {"RUNNING": list(running), "CYCLING": list(cycling)}
        self.weights = list(weights)
        self.calls = []

    def get_functional_threshold_power_range(self, start, end, *, sport, aggregation):
        self.calls.append((start, end, sport, aggregation))
        return [r for r in self.data[sport] if start <= r["from"] <= end]

    def get_body_composition(self, start, end):
        return {"dateWeightList": self.weights}


class API:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.writes = []

    def metrics(self):
        return self.rows

    def upsert_metric(self, metric):
        self.writes.append(metric.copy())
        self.rows = [r for r in self.rows if (r["date"][:10], r["type"]) != (metric["date"], metric["type"])]
        self.rows.append(metric.copy())
        return metric.copy()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("app.performance.time.sleep", lambda _: None)


def run(tmp_path, g, api, days=1, end=date(2026, 10, 20)):
    return sync_performance(SimpleNamespace(data_dir=tmp_path, health_lookback_days=days),
                            SimpleNamespace(client=g), api, end=end)


def test_measured_dates_sports_gaps_and_duplicate_records():
    start, end = date(2026, 10, 19), date(2026, 10, 20)
    rows = [row(), row(), row("2026-10-18"), row(updatedDate="2026-10-19")]
    assert ftp_records(rows, "CYCLING", start, end) == [{"date": "2026-10-20", "watts": 300}]
    assert ftp_records([], "RUNNING", start, end) == []
    assert ftp_records(None, "RUNNING", start, end) == []


@pytest.mark.parametrize("value", [None, True, False, 0, -1, float("nan"), float("inf"), "300"])
def test_invalid_ftp_values_are_not_imported(value):
    assert ftp_records([row(watts=value)], "CYCLING", date(2026, 10, 20), date(2026, 10, 20)) == []


@pytest.mark.parametrize("response", ["bad", {"bad": 1}, [None], [row(sport="RUNNING")],
                                    [row(until="2026-10-21")], [row(updatedDate=None)],
                                    [row(updatedDate="not-a-date")], [row(), row(watts=301)]])
def test_malformed_sport_date_and_conflicting_records_fail(response):
    with pytest.raises(ValueError):
        ftp_records(response, "CYCLING", date(2026, 10, 20), date(2026, 10, 20))


def test_ftp_units_same_day_weight_and_no_inferred_vma_or_critical_power(tmp_path):
    g = Garmin(running=[row(watts=350, sport="RUNNING")], cycling=[row(watts=250)],
               weights=[{"calendarDate": "2026-10-20", "weight": 68000},
                        {"calendarDate": "2026-10-20", "weight": 72000},
                        {"calendarDate": "2026-10-19", "weight": 100000},
                        {"calendarDate": "2026-10-20", "weight": float("nan")}])
    api = API()
    result = run(tmp_path, g, api)
    assert {m["type"]: m["value"] for m in api.rows} == {"FTP_RUNNING": 5, "FTP_CYCLING": 250}
    assert result["failures"] == 0 and result["written"] == 2
    assert result["unsupported"] == ["VMA", "CRITICAL_POWER_RUNNING", "CRITICAL_POWER_CYCLING"]
    assert all(m["notes"].startswith(SOURCE) for m in api.rows)
    assert not any("300" in m["notes"] or "350" in m["notes"] for m in api.rows)
    assert run(tmp_path, g, api)["unchanged"] == 2
    assert len(api.writes) == 2


def test_running_needs_same_day_weight_and_can_use_existing_weight(tmp_path):
    g = Garmin(running=[row(watts=350, sport="RUNNING")],
               weights=[{"calendarDate": "2026-10-19", "weight": 70000}])
    api = API()
    result = run(tmp_path, g, api)
    assert result["missing_running_weight"] == 1 and not api.writes
    api.rows.append({"date": "2026-10-20T00:00:00Z", "type": "WEIGHT", "value": 70})
    assert run(tmp_path, g, api)["written"] == 1
    assert api.writes[0]["type"] == "FTP_RUNNING" and api.writes[0]["value"] == 5


def test_manual_entries_preserved_and_own_values_corrected(tmp_path):
    g = Garmin(cycling=[row("2026-10-19", 250), row("2026-10-20", 300)])
    api = API([{"date": "2026-10-19", "type": "FTP_CYCLING", "value": 200, "notes": None},
               {"date": "2026-10-20", "type": "FTP_CYCLING", "value": 280, "notes": SOURCE}])
    report = run(tmp_path, g, api, days=2)
    assert report["preserved_manual"] == 1 and report["written"] == 1
    assert api.rows[0]["value"] == 200 and api.writes[0]["value"] == 300


def test_long_history_uses_nonoverlapping_366_day_batches(tmp_path):
    g, api = Garmin(), API()
    report = run(tmp_path, g, api, days=800)
    intervals = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b, s, agg in g.calls if s == "CYCLING"]
    assert len(intervals) == 3
    assert all(0 <= (b-a).days < 366 for a, b in intervals)
    assert all(intervals[i+1][1] == intervals[i][0] - timedelta(days=1) for i in range(2))
    assert intervals[-1][0].isoformat() == report["start"]
    assert {agg for _, _, _, agg in g.calls} == {"daily"}


@pytest.mark.parametrize("malformed", [False, True])
def test_failed_running_fetch_keeps_existing_and_imports_cycling(tmp_path, malformed):
    g = Garmin(cycling=[row()])
    fetch = g.get_functional_threshold_power_range
    def failure(start, end, *, sport, aggregation):
        if sport == "RUNNING":
            if malformed:
                return [{"unexpected": 1}]
            raise RuntimeError("Unavailable")
        return fetch(start, end, sport=sport, aggregation=aggregation)
    g.get_functional_threshold_power_range = failure
    old = {"date": "2026-10-20", "type": "FTP_RUNNING", "value": 5, "notes": SOURCE}
    api = API([old.copy()])
    with pytest.raises(RuntimeError, match="1 failures"):
        run(tmp_path, g, api)
    assert old in api.rows and api.writes[0]["type"] == "FTP_CYCLING"
    report = json.loads((tmp_path/"performance/last-report.json").read_text())
    assert report["failures"] == 1 and report["written"] == 1


def test_weight_fetch_failure_does_not_block_cycling(tmp_path):
    g = Garmin(running=[row(sport="RUNNING")], cycling=[row()])
    def fail(*args):
        raise RuntimeError("Unavailable")
    g.get_body_composition = fail
    api = API()
    with pytest.raises(RuntimeError, match="1 failures"):
        run(tmp_path, g, api)
    assert [r["type"] for r in api.writes] == ["FTP_CYCLING"]


def test_unexpected_api_response_is_reported_and_next_record_continues(tmp_path):
    g = Garmin(cycling=[row("2026-10-19"), row()])
    api = API()
    write = api.upsert_metric
    def changed(metric):
        return {} if metric["date"] == "2026-10-19" else write(metric)
    api.upsert_metric = changed
    with pytest.raises(RuntimeError, match="1 failures"):
        run(tmp_path, g, api, days=2)
    assert len(api.writes) == 1
