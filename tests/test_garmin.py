from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.garmin import GarminClient

FIT = b"\x0e" + b"\x00" * 7 + b".FIT" + b"\x00" * 8


def client_for(raw):
    client = object.__new__(GarminClient)
    client.client = SimpleNamespace(download_activity=lambda *args, **kwargs: raw)
    return client


def test_original_zip_is_extracted_without_using_archive_paths(tmp_path):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("../../outside.fit", FIT)
    path = tmp_path / "123.fit"
    client_for(buffer.getvalue()).download_fit("123", path)
    assert path.read_bytes() == FIT
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("raw", [b"not FIT", b"<xml/>"])
def test_invalid_download_not_archived(tmp_path, raw):
    path = tmp_path / "123.fit"
    with pytest.raises(ValueError):
        client_for(raw).download_fit("123", path)
    assert not path.exists()


def test_rejects_multiple_fits(tmp_path):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("1.fit", FIT)
        archive.writestr("2.fit", FIT)
    with pytest.raises(ValueError):
        client_for(buffer.getvalue()).download_fit("123", tmp_path / "123.fit")


def test_pagination_does_not_stop_at_page_size():
    pages = [[{"activityId": 1}, {"activityId": 2}], [{"activityId": 3}], []]
    calls = []
    def get(start, limit):
        calls.append(start)
        return pages.pop(0)
    client = object.__new__(GarminClient)
    client.client = SimpleNamespace(get_activities=get)
    assert len(list(client.recent(2))) == 3
    assert calls == [0, 2, 3]


def test_repeated_page_fails_instead_of_looping():
    client = object.__new__(GarminClient)
    client.client = SimpleNamespace(get_activities=lambda *args: [{"activityId": 1}])
    with pytest.raises(RuntimeError, match="repeated page"):
        list(client.recent(2))
