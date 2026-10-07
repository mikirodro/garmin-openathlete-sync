from pathlib import Path

from app.openathlete import OpenAthleteClient


class FakeResponse:
    status_code: int
    text = ""

    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("Request failed")

    def json(self):
        return {"eventId": 42}


class FakeSession:
    def __init__(self):
        self.calls = []
        self.responses = [FakeResponse(401), FakeResponse(201)]

    def post(self, url, **kwargs):
        file_name, file_handle, mimetype = kwargs["files"]["file"]
        self.calls.append(
            {
                "url": url,
                "authorization": kwargs["headers"]["Authorization"],
                "filename": file_name,
                "content": file_handle.read(),
                "mimetype": mimetype,
                "timeout": kwargs["timeout"],
                "name": kwargs["data"]["name"],
            }
        )
        return self.responses.pop(0)


def test_import_fit_uploads_file_and_retries_after_refresh(
    tmp_path: Path, monkeypatch
):
    fit_path = tmp_path / "activity.fit"
    fit_path.write_bytes(b"synthetic FIT")

    client = OpenAthleteClient("http://openathlete", "email", "password")
    client.access = "expired"
    session = FakeSession()
    client.s = session
    monkeypatch.setattr(client, "refresh", lambda: setattr(client, "access", "fresh"))

    result = client.import_fit(fit_path, "Morning run")

    assert result == {"eventId": 42}
    assert [call["authorization"] for call in session.calls] == [
        "Bearer expired",
        "Bearer fresh",
    ]
    assert [call["content"] for call in session.calls] == [
        b"synthetic FIT",
        b"synthetic FIT",
    ]
    assert all(call["url"] == "http://openathlete/activity-import/fit" for call in session.calls)
    assert all(call["filename"] == "activity.fit" for call in session.calls)
    assert all(
        call["mimetype"] == "application/vnd.garmin.fit"
        for call in session.calls
    )

    assert all(call["name"] == "Morning run" for call in session.calls)
