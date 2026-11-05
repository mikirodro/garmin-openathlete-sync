"""Report health only after a complete successful scheduled sync."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def healthy(path, interval, now=None):
    try:
        data = json.loads(path.read_text())
        checked = datetime.fromisoformat(data['checked_at'])
        age = ((now or datetime.now(timezone.utc)) - checked).total_seconds()
        return data['status'] == 'ok' and 0 <= age <= max(600, 2 * interval + 600)
    except (OSError, ValueError, TypeError, KeyError):
        return False


if __name__ == '__main__':
    try:
        interval = int(os.getenv('SYNC_INTERVAL_SECONDS', '86400'))
        ok = interval > 0 and healthy(Path(os.getenv('DATA_DIR', '/data')) / 'cycle-status.json', interval)
    except ValueError:
        ok = False
    sys.exit(0 if ok else 1)
