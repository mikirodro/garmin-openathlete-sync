import re
from pathlib import Path

import pytest

from app import __version__
from app.sync import main

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_changelog_documents_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in changelog


def test_version_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["app", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out
