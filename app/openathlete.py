from pathlib import Path

import requests
import time

from .config import validate_base_url


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
