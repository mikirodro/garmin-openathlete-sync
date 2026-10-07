import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def secret(name):
    path = os.getenv(name + "_FILE")
    return Path(path).read_text(encoding="utf-8").strip() if path else os.getenv(name, "")


@dataclass(frozen=True)
class Config:
    garmin_email: str
    garmin_password: str
    openathlete_base_url: str
    openathlete_email: str
    openathlete_password: str
    sync_interval: int
    activity_limit: int
    lookback_days: int
    data_dir: Path

    @classmethod
    def from_env(cls):
        c = cls(
            os.getenv("GARMIN_EMAIL", ""), secret("GARMIN_PASSWORD"),
            os.getenv("OPENATHLETE_BASE_URL", "http://api:3000").rstrip("/"),
            os.getenv("OPENATHLETE_EMAIL", ""), secret("OPENATHLETE_PASSWORD"),
            int(os.getenv("SYNC_INTERVAL_SECONDS", "86400")),
            int(os.getenv("GARMIN_ACTIVITY_LIMIT", "100")),
            int(os.getenv("GARMIN_ACTIVITY_LOOKBACK_DAYS", "7")),
            Path(os.getenv("DATA_DIR", "./data")),
        )
        missing = [key for key, value in {
            "GARMIN_EMAIL": c.garmin_email, "GARMIN_PASSWORD": c.garmin_password,
            "OPENATHLETE_EMAIL": c.openathlete_email,
            "OPENATHLETE_PASSWORD": c.openathlete_password,
        }.items() if not value]
        if missing:
            raise ValueError("Missing configuration: " + ", ".join(missing))
        url = urlsplit(c.openathlete_base_url)
        if url.scheme not in ("http", "https") or not url.netloc or url.query or url.fragment:
            raise ValueError("OPENATHLETE_BASE_URL must be an HTTP(S) API URL")
        if c.sync_interval <= 0 or not 1 <= c.activity_limit <= 1000 or c.lookback_days <= 0:
            raise ValueError("Interval/lookback must be positive; page size must be 1..1000")
        c.data_dir.mkdir(parents=True, exist_ok=True)
        return c
