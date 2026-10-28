import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def secret(name):
    path = os.getenv(name + "_FILE")
    return Path(path).read_text(encoding="utf-8").strip() if path else os.getenv(name, "")


@dataclass(frozen=True)
class Config:
    garmin_email: str
    garmin_password: str = field(repr=False)
    openathlete_base_url: str
    openathlete_email: str
    openathlete_password: str = field(repr=False)
    sync_interval: int
    activity_limit: int
    lookback_days: int
    data_dir: Path
    health_lookback_days: int = 7
    planned_days: int = 90
    allow_insecure_http: bool = False

    @classmethod
    def from_env(cls):
        c = cls(
            os.getenv("GARMIN_EMAIL", ""), secret("GARMIN_PASSWORD"),
            os.getenv("OPENATHLETE_BASE_URL", "").rstrip("/"),
            os.getenv("OPENATHLETE_EMAIL", ""), secret("OPENATHLETE_PASSWORD"),
            int(os.getenv("SYNC_INTERVAL_SECONDS", "86400")),
            int(os.getenv("GARMIN_ACTIVITY_LIMIT", "100")),
            int(os.getenv("GARMIN_ACTIVITY_LOOKBACK_DAYS", "7")),
            Path(os.getenv("DATA_DIR", "./data")),
            int(os.getenv("GARMIN_HEALTH_LOOKBACK_DAYS", "7")),
            int(os.getenv("GARMIN_PLANNED_DAYS", "90")),
            boolean("ALLOW_INSECURE_HTTP"),
        )
        missing = [key for key, value in {
            "GARMIN_EMAIL": c.garmin_email, "GARMIN_PASSWORD": c.garmin_password,
            "OPENATHLETE_BASE_URL": c.openathlete_base_url,
            "OPENATHLETE_EMAIL": c.openathlete_email,
            "OPENATHLETE_PASSWORD": c.openathlete_password,
        }.items() if not value]
        if missing:
            raise ValueError("Missing configuration: " + ", ".join(missing))
        validate_base_url(c.openathlete_base_url, c.allow_insecure_http)
        if c.sync_interval <= 0 or not 1 <= c.activity_limit <= 1000 or c.lookback_days <= 0 or c.health_lookback_days <= 0:
            raise ValueError("Interval/lookback must be positive; page size must be 1..1000")
        if not 1 <= c.planned_days <= 366:
            raise ValueError("GARMIN_PLANNED_DAYS must be 1..366")
        c.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return c


def boolean(name):
    value = os.getenv(name, "false").lower()
    if value not in ("true", "false"):
        raise ValueError(name + " must be true or false")
    return value == "true"


def validate_base_url(value, allow_insecure_http=False):
    url = urlsplit(value)
    if (url.scheme not in ("http", "https") or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment):
        raise ValueError("OPENATHLETE_BASE_URL must be an HTTP(S) API URL without credentials")
    try:
        url.port
    except ValueError:
        raise ValueError("OPENATHLETE_BASE_URL has an invalid port") from None
    if url.scheme == "http" and not allow_insecure_http:
        raise ValueError("HTTPS required; ALLOW_INSECURE_HTTP=true is only for trusted local networks")
