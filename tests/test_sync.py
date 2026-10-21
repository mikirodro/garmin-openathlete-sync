from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.sync import run_once, run_cycle


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
    monkeypatch.setattr("app.sync.sync_health", lambda *args, **kwargs: called.append("health"))
    monkeypatch.setattr("app.sync.sync_planned", lambda *args, **kwargs: called.append("planned"))
    with pytest.raises(RuntimeError, match="1 sync stages failed"):
        run_cycle(None, SimpleNamespace(client=object()), None, None)
    assert called == ["health", "planned"]
