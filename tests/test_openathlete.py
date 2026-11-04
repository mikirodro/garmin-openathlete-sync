from pathlib import Path

from app.openathlete import OpenAthleteClient, error_summary


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

    client = OpenAthleteClient("https://openathlete", "email", "password")
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
    assert all(call["url"] == "https://openathlete/activity-import/fit" for call in session.calls)
    assert all(call["filename"] == "activity.fit" for call in session.calls)
    assert all(
        call["mimetype"] == "application/vnd.garmin.fit"
        for call in session.calls
    )

    assert all(call["name"] == "Morning run" for call in session.calls)


def test_metric_api_refreshes_expired_token(monkeypatch):
    client = OpenAthleteClient("https://openathlete", "email", "password")
    client.access = "expired"
    calls = []
    responses = [FakeResponse(401), FakeResponse(201)]
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return responses.pop(0)
    monkeypatch.setattr(client.s, "request", request)
    monkeypatch.setattr(client, "refresh", lambda: setattr(client, "access", "fresh"))
    metric = {"type": "WEIGHT", "date": "2026-10-20", "value": 71}
    client.upsert_metric(metric)
    assert [c[2]["headers"]["Authorization"] for c in calls] == ["Bearer expired", "Bearer fresh"]
    assert all(c[0:2] == ("POST", "https://openathlete/metric") and c[2]["json"] == metric for c in calls)


def test_metric_api_obeys_retry_after_without_changing_payload(monkeypatch):
    client = OpenAthleteClient("https://openathlete", "email", "password")
    client.access = "valid"
    limited = FakeResponse(429)
    limited.headers = {"Retry-After": "3"}
    responses = [limited, FakeResponse(201)]
    payloads, sleeps = [], []
    def request(method, url, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)
    monkeypatch.setattr(client.s, "request", request)
    monkeypatch.setattr("app.openathlete.time.sleep", sleeps.append)
    metric = {"type": "WEIGHT", "date": "2026-10-20", "value": 71}
    client.upsert_metric(metric)
    assert sleeps == [3.25] and payloads == [metric, metric]


class ErrorResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class HTTPFailure(Exception):
    def __init__(self, response):
        super().__init__("failure")
        self.response = response


def test_error_summary_reports_status_and_api_code():
    error = HTTPFailure(ErrorResponse(409, {"statusCode": 409, "code": "FIT_DUPLICATE_TIME"}))
    assert error_summary(error) == "HTTPFailure, HTTP 409, FIT_DUPLICATE_TIME"


def test_error_summary_accepts_code_in_message_list():
    error = HTTPFailure(ErrorResponse(422, {"message": ["FIT_NO_STREAM"], "error": "Unprocessable Entity"}))
    assert error_summary(error) == "HTTPFailure, HTTP 422, FIT_NO_STREAM"


def test_error_summary_never_logs_free_text_or_bodies():
    error = HTTPFailure(ErrorResponse(400, {"message": "Activity 'Run near home' by user@example.invalid"}))
    assert error_summary(error) == "HTTPFailure, HTTP 400"
    assert error_summary(HTTPFailure(ErrorResponse(502, ValueError("not json")))) == "HTTPFailure, HTTP 502"
    assert error_summary(ValueError("secret detail")) == "ValueError"
