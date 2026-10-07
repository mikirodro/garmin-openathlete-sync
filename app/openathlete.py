from pathlib import Path

import requests


class OpenAthleteClient:
    def __init__(self, base_url, email, password):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.s = requests.Session()
        self.access = ""
        self.refresh_token = ""

    def login(self):
        if self.access:
            return
        self._login()

    def _login(self):
        r = self.s.post(
            self.base_url + "/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=30,
        )
        r.raise_for_status()
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
            timeout=30,
        )
        if r.status_code >= 400:
            self.access = ""
            self.refresh_token = ""
            self._login()
            return
        r.raise_for_status()
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
                    timeout=120,
                )

        self.login()
        r = upload()
        if r.status_code == 401:
            self.refresh()
            r = upload()
        r.raise_for_status()
        return r.json()
