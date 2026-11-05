import re
import time
from pathlib import Path

import requests

from .config import validate_base_url


ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


PERMANENT_STATUSES = {400, 409, 413, 422}


def api_code(response):
    """Machine-readable API code such as FIT_DUPLICATE_TIME, never free text."""
    try:
        data = response.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # Messages may contain personal data: only accept code-shaped values.
    for key in ("code", "errorCode", "message", "error"):
        values = data.get(key)
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str) and ERROR_CODE.fullmatch(value):
                return value
    return None


def error_summary(error):
    """Exception type, HTTP status and API error code; never response bodies."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        return type(error).__name__
    code = api_code(response)
    return ", ".join([type(error).__name__, f"HTTP {status}"] + ([code] if code else []))


def rejection_code(error):
    """API code when OpenAthlete rejected the file itself; None for retryable errors."""
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) not in PERMANENT_STATUSES:
        return None
    return api_code(response)


class OpenAthleteClient:
    def __init__(self, base_url, email, password, *, allow_insecure_http=False):
        validate_base_url(base_url, allow_insecure_http)
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.s = requests.Session()
        self.access = ""
        self.refresh_token = ""

    @staticmethod
    def _check_response(response):
        if 300 <= response.status_code < 400:
            raise requests.HTTPError("API redirects are disabled", response=response)
        response.raise_for_status()

    def login(self):
        if self.access:
            return
        self._login()

    def _login(self):
        r = self.s.post(
            self.base_url + "/auth/login",
            json={"email": self.email, "password": self.password},
            allow_redirects=False,
            timeout=30,
        )
        self._check_response(r)
        data = r.json()
        self.access = data["accessToken"]
        self.refresh_token = data["refreshToken"]

    def refresh(self):
        if not self.refresh_token:
            self._login()
            return
        r = self.s.post(
            self.base_url + "/auth/refresh-token",
            json={"refreshToken": self.refresh_token},
            allow_redirects=False,
            timeout=30,
        )
        if 300 <= r.status_code < 400:
            self._check_response(r)
        if r.status_code >= 400:
            self.access = ""
            self.refresh_token = ""
            self._login()
            return
        self._check_response(r)
        data = r.json()
        self.access = data["accessToken"]
        self.refresh_token = data["refreshToken"]

    def import_fit(self, file_path: Path, name: str):
        def upload():
            with file_path.open("rb") as activity_file:
                return self.s.post(
                    self.base_url + "/activity-import/fit",
                    data={"name": (name.strip() or "Garmin activity")[:100]},
                    files={
                        "file": (
                            file_path.name,
                            activity_file,
                            "application/vnd.garmin.fit",
                        )
                    },
                    headers={"Authorization": "Bearer " + self.access},
                    allow_redirects=False,
                    timeout=120,
                )

        self.login()
        r = upload()
        if r.status_code == 401:
            self.refresh()
            r = upload()
        self._check_response(r)
        return r.json()

    def metric_request(self, method, path="/metric", **kwargs):
        self.login()
        def request():
            for attempt in range(7):
                response = self.s.request(method, self.base_url + path,
                                          headers={"Authorization": "Bearer " + self.access},
                                          allow_redirects=False, timeout=30, **kwargs)
                if response.status_code != 429 or attempt == 6:
                    return response
                try:
                    delay = float(response.headers.get("Retry-After", 2 ** attempt))
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                time.sleep(min(60, max(1, delay)) + .25)
        r = request()
        if r.status_code == 401:
            self.refresh()
            r = request()
        self._check_response(r)
        return r.json()

    def metrics(self):
        return self.metric_request("GET")

    def upsert_metric(self, metric):
        return self.metric_request("POST", json=metric)
