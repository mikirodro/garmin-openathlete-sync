import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from app.config import Config, validate_base_url
from app.openathlete import OpenAthleteClient
from app.security import single_instance


@pytest.mark.parametrize('url', ['http://api:3000', 'https://user:password@example.invalid',
                                 'https://example.invalid/?x=y', 'https://example.invalid/#fragment',
                                 'https://example.invalid:bad', 'file:///tmp/api', ''])
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_local_http_requires_explicit_consent():
    with pytest.raises(ValueError):
        OpenAthleteClient('http://api:3000', 'test', 'synthetic')
    client = OpenAthleteClient('http://api:3000', 'test', 'synthetic', allow_insecure_http=True)
    assert client.base_url == 'http://api:3000'


def config_environment(monkeypatch, tmp_path):
    for key in ('GARMIN_EMAIL', 'GARMIN_PASSWORD', 'OPENATHLETE_EMAIL', 'OPENATHLETE_PASSWORD'):
        monkeypatch.setenv(key, 'synthetic-secret')
        monkeypatch.delenv(key + '_FILE', raising=False)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('OPENATHLETE_BASE_URL', 'https://example.invalid')
    monkeypatch.delenv('ALLOW_INSECURE_HTTP', raising=False)


def test_required_url_hidden_secrets_and_file_precedence(monkeypatch, tmp_path):
    config_environment(monkeypatch, tmp_path)
    secret = tmp_path / 'secret'
    secret.write_text('file-secret\n')
    monkeypatch.setenv('GARMIN_PASSWORD_FILE', str(secret))
    c = Config.from_env()
    assert c.garmin_password == 'file-secret'
    assert 'file-secret' not in repr(c)
    # Emails still appear, but password fields must never be represented.
    assert 'garmin_password=' not in repr(c) and 'openathlete_password=' not in repr(c)
    monkeypatch.delenv('OPENATHLETE_BASE_URL')
    with pytest.raises(ValueError, match='OPENATHLETE_BASE_URL'):
        Config.from_env()


def test_http_config_boolean_is_strict(monkeypatch, tmp_path):
    config_environment(monkeypatch, tmp_path)
    monkeypatch.setenv('OPENATHLETE_BASE_URL', 'http://api:3000')
    with pytest.raises(ValueError, match='HTTPS'):
        Config.from_env()
    monkeypatch.setenv('ALLOW_INSECURE_HTTP', 'true')
    assert Config.from_env().allow_insecure_http
    monkeypatch.setenv('ALLOW_INSECURE_HTTP', 'yes')
    with pytest.raises(ValueError, match='true or false'):
        Config.from_env()


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
@pytest.mark.parametrize('operation', ['login', 'refresh', 'import', 'metric'])
def test_every_authenticated_operation_disables_and_rejects_redirects(monkeypatch, tmp_path, status, operation):
    client = OpenAthleteClient('https://example.invalid', 'test', 'synthetic-secret')
    client.access = 'synthetic-access'
    client.refresh_token = 'synthetic-refresh'
    calls = []

    def respond(method, url, **kwargs):
        calls.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = status
        response.headers['Location'] = 'https://other.invalid/receive'
        return response

    monkeypatch.setattr(client.s, 'request', respond)
    fit = tmp_path / 'synthetic.fit'
    fit.write_bytes(b'synthetic')
    operations = {'login': client._login, 'refresh': client.refresh,
                  'import': lambda: client.import_fit(fit, 'synthetic'),
                  'metric': client.metrics}
    with pytest.raises(requests.HTTPError, match='redirects are disabled'):
        operations[operation]()
    assert len(calls) == 1
    assert calls[0][2]['allow_redirects'] is False


def test_lock_excludes_other_process_and_releases_after_exit(tmp_path):
    script = ('from pathlib import Path; from app.security import single_instance; '
              'import sys; '\
              '\ntry:\n with single_instance(Path(sys.argv[1])): pass'
              '\nexcept RuntimeError: sys.exit(23)')
    with single_instance(tmp_path):
        result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True)
        assert result.returncode == 23, result.stderr.decode()
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / '.sync.lock').stat().st_mode) == 0o600


def test_lock_does_not_follow_symlinks(tmp_path):
    target = tmp_path / 'target'
    target.write_text('unchanged')
    (tmp_path / '.sync.lock').symlink_to(target)
    with pytest.raises(OSError):
        with single_instance(tmp_path):
            pytest.fail('must not enter')
    assert target.read_text() == 'unchanged'


@pytest.mark.parametrize('mode', ['--login', '--once', '--health-only', '--performance-only', '--planned-only', '--rpe-backfill'])
def test_cli_sets_private_creation_mask_and_locks_before_clients(monkeypatch, tmp_path, mode):
    import app.sync as sync
    from contextlib import contextmanager
    calls = []
    config = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr(sync.Config, 'from_env', lambda: config)

    @contextmanager
    def lock(path):
        calls.append('lock')
        yield
        calls.append('unlock')

    def run(c, args):
        assert calls == ['lock']
        sample = tmp_path / 'private'
        sample.write_text('synthetic')
        assert stat.S_IMODE(sample.stat().st_mode) == 0o600
        calls.append('run')

    monkeypatch.setattr(sync, 'single_instance', lock)
    monkeypatch.setattr(sync, 'run_configured', run)
    monkeypatch.setattr(sys, 'argv', ['app', mode])
    old = os.umask(0o022)
    try:
        sync.main()
    finally:
        os.umask(old)
    assert calls == ['lock', 'run', 'unlock']
