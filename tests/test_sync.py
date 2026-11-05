from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.state import State
from app.sync import retry_rejected, run_once, run_cycle


class FakeGarmin:
    def __init__(self):
        self.activity_id = "12345"

    def login(self):
        pass

    def recent(self, _limit: int):
        return [
            {
                "activityId": self.activity_id,
                "startTimeGMT": datetime.now(timezone.utc).isoformat(),
            }
        ]

    def download_fit(self, _activity_id: str, out: Path):
        out.write_bytes(b"synthetic FIT")


class FakeOpenAthlete:
    def __init__(self, fail_import: bool = False):
        self.fail_import = fail_import
        self.imported_files: list[Path] = []

    def login(self):
        pass

    def import_fit(self, file_path: Path, name: str):
        self.imported_files.append(file_path)
        if self.fail_import:
            raise RuntimeError("OpenAthlete is unavailable")
        return {"eventId": 42}


class FakeState:
    def __init__(self):
        self.added = []

    def contains(self, activity_id: str) -> bool:
        return any(entry[0] == activity_id for entry in self.added)

    def add(self, activity_id: str, openathlete_id, synced_at: str):
        self.added.append((activity_id, openathlete_id, synced_at))

    def rejected(self, activity_id: str) -> bool:
        return activity_id in getattr(self, "rejections", {})

    def reject(self, activity_id: str, code: str, _when: str):
        self.rejections = getattr(self, "rejections", {})
        self.rejections[activity_id] = code


def test_run_once_uploads_downloaded_fit_and_records_success(tmp_path: Path):
    config = SimpleNamespace(
        data_dir=tmp_path,
        lookback_days=7,
        activity_limit=10,
    )
    garmin = FakeGarmin()
    openathlete = FakeOpenAthlete()
    state = FakeState()

    imported = run_once(config, garmin, openathlete, state)

    fit_path = tmp_path / "activities" / "12345.fit"
    assert imported == 1
    assert fit_path.read_bytes() == b"synthetic FIT"
    assert openathlete.imported_files == [fit_path]
    assert state.added[0][0:2] == ("12345", 42)


def test_run_once_keeps_fit_and_does_not_record_failed_upload(tmp_path: Path):
    config = SimpleNamespace(
        data_dir=tmp_path,
        lookback_days=7,
        activity_limit=10,
    )
    state = FakeState()

    with pytest.raises(RuntimeError, match="1 activities failed"):
        run_once(config, FakeGarmin(), FakeOpenAthlete(fail_import=True), state)
    assert (tmp_path / "activities" / "12345.fit").is_file()
    assert state.added == []


def test_pending_archive_retried_outside_lookback(tmp_path):
    folder = tmp_path / "activities"
    folder.mkdir()
    (folder / "999.fit").write_bytes(b"synthetic FIT")
    config = SimpleNamespace(data_dir=tmp_path, lookback_days=7, activity_limit=10)
    state = FakeState()
    assert run_once(config, FakeGarmin(), FakeOpenAthlete(), state) == 2
    assert state.contains("999")


def test_processing_not_queued_is_retried_without_redownload(tmp_path):
    config = SimpleNamespace(data_dir=tmp_path, lookback_days=7, activity_limit=10)
    state = FakeState()
    api = FakeOpenAthlete()
    api.import_fit = lambda *args: {"eventId": 42, "processingQueued": False}
    with pytest.raises(RuntimeError):
        run_once(config, FakeGarmin(), api, state)
    assert not state.added
    garmin = FakeGarmin()
    garmin.download_fit = lambda *args: pytest.fail("must reuse archived bytes")
    assert run_once(config, garmin, FakeOpenAthlete(), state) == 1


def test_prefers_gmt_and_stops_after_cutoff(tmp_path):
    config = SimpleNamespace(data_dir=tmp_path, lookback_days=7, activity_limit=10)
    garmin = FakeGarmin()
    garmin.recent = lambda limit: [{"activityId": "9", "startTimeGMT": "2000-01-01T00:00:00", "startTimeLocal": datetime.now(timezone.utc).isoformat()}]
    garmin.download_fit = lambda *args: pytest.fail("old activity must be skipped")
    assert run_once(config, garmin, FakeOpenAthlete(), FakeState()) == 0


def test_synced_activity_is_not_uploaded_again(tmp_path):
    config = SimpleNamespace(data_dir=tmp_path, lookback_days=7, activity_limit=10)
    state = FakeState()
    api = FakeOpenAthlete()
    assert run_once(config, FakeGarmin(), api, state) == 1
    assert run_once(config, FakeGarmin(), api, state) == 0
    assert len(api.imported_files) == 1


def test_health_runs_even_if_activity_stage_fails(monkeypatch):
    called = []
    def fail(*args):
        raise RuntimeError("Activity unavailable")
    monkeypatch.setattr("app.sync.run_once", fail)
    monkeypatch.setattr("app.sync.sync_rpe", lambda *args, **kwargs: called.append("rpe"))
    monkeypatch.setattr("app.sync.sync_health", lambda *args, **kwargs: called.append("health"))
    monkeypatch.setattr("app.sync.sync_performance", lambda *args, **kwargs: called.append("performance"))
    monkeypatch.setattr("app.sync.sync_planned", lambda *args, **kwargs: called.append("planned"))
    with pytest.raises(RuntimeError, match="1 sync stages failed"):
        run_cycle(None, SimpleNamespace(client=object()), SimpleNamespace(login=lambda: None), None)
    assert called == ["rpe", "health", "performance", "planned"]


def test_ftp_failure_does_not_block_planned_workouts(monkeypatch):
    called = []
    monkeypatch.setattr("app.sync.run_once", lambda *args: 0)
    monkeypatch.setattr("app.sync.sync_rpe", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.sync.sync_health", lambda *args, **kwargs: None)
    def fail(*args, **kwargs):
        raise RuntimeError("FTP unavailable")
    monkeypatch.setattr("app.sync.sync_performance", fail)
    monkeypatch.setattr("app.sync.sync_planned", lambda *args, **kwargs: called.append("planned"))
    with pytest.raises(RuntimeError, match="1 sync stages failed"):
        run_cycle(None, SimpleNamespace(client=object()), SimpleNamespace(login=lambda: None), None)
    assert called == ["planned"]


def test_performance_only_cli_avoids_other_imports_and_sqlite(tmp_path, monkeypatch):
    from app.sync import main
    config = SimpleNamespace(garmin_email="", garmin_password="", data_dir=tmp_path,
                             openathlete_base_url="", openathlete_email="", openathlete_password="")
    monkeypatch.setattr("app.sync.Config.from_env", lambda: config)
    client = SimpleNamespace(login=lambda: None)
    monkeypatch.setattr("app.sync.GarminClient", lambda *args, **kwargs: client)
    monkeypatch.setattr("app.sync.OpenAthleteClient", lambda *args, **kwargs: client)
    monkeypatch.setattr("app.sync.State", lambda *args: pytest.fail("FTP-only must not open SQLite"))
    calls = []
    monkeypatch.setattr("app.sync.sync_performance", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr("sys.argv", ["app", "--performance-only", "--health-days", "1000"])
    main()
    assert calls == [{"days": 1000}]


def test_rpe_failure_does_not_block_other_stages(monkeypatch):
    called = []
    monkeypatch.setattr("app.sync.run_once", lambda *args: 0)
    def fail(*args, **kwargs):
        raise RuntimeError("RPE unavailable")
    monkeypatch.setattr("app.sync.sync_rpe", fail)
    monkeypatch.setattr("app.sync.sync_health", lambda *args, **kwargs: called.append("health"))
    monkeypatch.setattr("app.sync.sync_performance", lambda *args, **kwargs: called.append("performance"))
    monkeypatch.setattr("app.sync.sync_planned", lambda *args, **kwargs: called.append("planned"))
    with pytest.raises(RuntimeError, match="1 sync stages failed"):
        run_cycle(None, SimpleNamespace(client=object()), SimpleNamespace(login=lambda: None), None)
    assert called == ["health", "performance", "planned"]


def test_rpe_backfill_cli_only_runs_rpe(tmp_path, monkeypatch):
    from app.sync import main
    config = SimpleNamespace(garmin_email="", garmin_password="", data_dir=tmp_path,
                             openathlete_base_url="", openathlete_email="", openathlete_password="")
    monkeypatch.setattr("app.sync.Config.from_env", lambda: config)
    client = SimpleNamespace(login=lambda: None)
    monkeypatch.setattr("app.sync.GarminClient", lambda *args, **kwargs: client)
    monkeypatch.setattr("app.sync.OpenAthleteClient", lambda *args, **kwargs: client)
    calls = []
    monkeypatch.setattr("app.sync.sync_rpe", lambda *args, **kwargs: calls.append(kwargs))
    for function in ("run_once", "sync_health", "sync_performance", "sync_planned"):
        monkeypatch.setattr("app.sync." + function, lambda *args, **kwargs: pytest.fail("Unexpected sync stage"))
    monkeypatch.setattr("sys.argv", ["app", "--rpe-backfill"])
    main()
    assert calls == [{"backfill": True}]


class ApiResponse:
    def __init__(self, status_code, code):
        self.status_code = status_code
        self.code = code

    def json(self):
        return {"statusCode": self.status_code, "code": self.code}


class ApiError(Exception):
    def __init__(self, status_code, code):
        super().__init__("synthetic API error")
        self.response = ApiResponse(status_code, code)


class RejectingOpenAthlete(FakeOpenAthlete):
    def __init__(self, status_code, code):
        super().__init__()
        self.error = ApiError(status_code, code)

    def import_fit(self, file_path: Path, name: str):
        self.imported_files.append(file_path)
        raise self.error


def lookback_config(tmp_path):
    return SimpleNamespace(data_dir=tmp_path, lookback_days=7, activity_limit=10)


@pytest.mark.parametrize("status,code", [(400, "FIT_INVALID"), (400, "FIT_MULTISPORT_UNSUPPORTED"),
                                         (409, "FIT_DUPLICATE_TIME")])
def test_permanent_rejection_is_quarantined_not_failed(tmp_path, status, code):
    state = FakeState()
    api = RejectingOpenAthlete(status, code)
    assert run_once(lookback_config(tmp_path), FakeGarmin(), api, state) == 0
    rejected = tmp_path / "activities" / "rejected"
    assert (rejected / "12345.fit").read_bytes() == b"synthetic FIT"
    assert (rejected / "12345.name.txt").exists()
    assert not (tmp_path / "activities" / "12345.fit").exists()
    assert state.rejections == {"12345": code}
    # Not retried from the archive nor downloaded again while still in the lookback window.
    assert run_once(lookback_config(tmp_path), FakeGarmin(), api, state) == 0
    assert len(api.imported_files) == 1


@pytest.mark.parametrize("status,code", [(503, "SERVICE_UNAVAILABLE"), (429, "TOO_MANY_REQUESTS"), (400, None)])
def test_transient_or_unknown_errors_remain_retryable(tmp_path, status, code):
    state = FakeState()
    with pytest.raises(RuntimeError, match="1 activities failed"):
        run_once(lookback_config(tmp_path), FakeGarmin(), RejectingOpenAthlete(status, code), state)
    assert (tmp_path / "activities" / "12345.fit").exists()
    assert not (tmp_path / "activities" / "rejected").exists()
    assert not state.rejected("12345")


def test_retry_rejected_requeues_files_and_clears_state(tmp_path):
    state = State(tmp_path / "state.sqlite3")
    api = RejectingOpenAthlete(409, "FIT_DUPLICATE_TIME")
    run_once(lookback_config(tmp_path), FakeGarmin(), api, state)
    assert state.rejected("12345")
    assert retry_rejected(lookback_config(tmp_path), state) == ["12345"]
    assert not state.rejected("12345")
    assert (tmp_path / "activities" / "12345.fit").exists()
    assert (tmp_path / "activities" / "12345.name.txt").exists()
    # Once the duplicate is resolved, the archived FIT imports normally.
    assert run_once(lookback_config(tmp_path), FakeGarmin(), FakeOpenAthlete(), state) == 1
    assert state.contains("12345")


def test_retry_rejected_cli_only_requeues(tmp_path, monkeypatch):
    from app.sync import main
    config = SimpleNamespace(garmin_email="", garmin_password="", data_dir=tmp_path,
                             openathlete_base_url="", openathlete_email="", openathlete_password="")
    monkeypatch.setattr("app.sync.Config.from_env", lambda: config)
    client = SimpleNamespace(login=lambda: pytest.fail("--retry-rejected must not contact accounts"))
    monkeypatch.setattr("app.sync.GarminClient", lambda *args, **kwargs: client)
    monkeypatch.setattr("app.sync.OpenAthleteClient", lambda *args, **kwargs: client)
    calls = []
    monkeypatch.setattr("app.sync.retry_rejected", lambda *args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["app", "--retry-rejected"])
    main()
    assert len(calls) == 1
