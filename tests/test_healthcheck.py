from datetime import datetime, timedelta, timezone

from app.healthcheck import healthy
from app.sync import write_status


def test_status_detects_failure_and_staleness(tmp_path):
    path = tmp_path / 'cycle-status.json'
    assert not healthy(path, 60)
    write_status(tmp_path, 'ok')
    assert healthy(path, 60)
    assert not healthy(path, 60, datetime.now(timezone.utc) + timedelta(hours=1))
    write_status(tmp_path, 'failed')
    assert not healthy(path, 60)
    assert 'last_success' in path.read_text()
