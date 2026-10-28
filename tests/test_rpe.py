from types import SimpleNamespace
import pytest
from app.rpe import normalize, sync_one, sync_rpe
from app.state import State

class Garmin:
    def __init__(self, value):
        self.value = value
        self.client = self
    def get_activity(self, gid):
        return {'summaryDTO': {'directWorkoutRpe': self.value}}

class API:
    def __init__(self, value=None):
        self.value = value
        self.patches = []
    def metric_request(self, method, path, **kwargs):
        if method == 'PATCH':
            assert kwargs['json']['type'] == 'ACTIVITY'
            self.value = kwargs['json']['rpe']
            self.patches.append(self.value)
        return {'type': 'ACTIVITY', 'rpe': self.value}

@pytest.mark.parametrize('raw,expected', [(None,None),(0,0),(30,.3),(70,.7),(100,1)])
def test_scale(raw, expected):
    assert normalize(raw) == expected

@pytest.mark.parametrize('raw', [-1,101,True,'70',float('nan')])
def test_reject_bad_scale(raw):
    with pytest.raises(ValueError): normalize(raw)

def test_import_update_preserve_manual_and_clear(tmp_path):
    s=State(tmp_path/'state.db'); g=Garmin(70); a=API()
    assert sync_one(g,a,s,'1','2') == 'written'
    assert a.value == .7
    g.value=80
    assert sync_one(g,a,s,'1','2') == 'written'
    assert a.value == .8
    a.value=.5; g.value=90
    assert sync_one(g,a,s,'1','2') == 'preserved_manual'
    assert a.value == .5
    a.value=None
    assert sync_one(g,a,s,'1','2') == 'preserved_manual'
    assert a.patches == [.7,.8]

def test_existing_equal_not_claimed(tmp_path):
    s=State(tmp_path/'state.db'); a=API(.7); g=Garmin(70)
    assert sync_one(g,a,s,'1','2') == 'unchanged'
    g.value=80
    assert sync_one(g,a,s,'1','2') == 'preserved_manual'
    assert a.patches == []

def test_backfill_resumes_and_missing_does_not_clear(tmp_path,monkeypatch):
    s=State(tmp_path/'state.db'); s.add('1',2,'2026-01-01'); s.add('3',4,'2026-01-01')
    monkeypatch.setattr('app.rpe.time.sleep', lambda _:None)
    assert sync_rpe(None,Garmin(None),API(.3),s,backfill=True)['missing']==2
    assert sync_rpe(None,Garmin(70),API(),s,backfill=True)['written']==0
    assert len(s.rpe_oldest_candidates(20))==2


def test_manual_clear_is_permanent_even_when_old_value_is_restored(tmp_path):
    state = State(tmp_path / 'state.db')
    garmin, api = Garmin(70), API()
    assert sync_one(garmin, api, state, '1', '2') == 'written'
    api.value = None
    garmin.value = 80
    assert sync_one(garmin, api, state, '1', '2') == 'preserved_manual'
    assert state.rpe_manual('1', '2')
    api.value = .7
    assert sync_one(garmin, api, state, '1', '2') == 'preserved_manual'
    assert api.patches == [.7]


def test_missing_garmin_value_does_not_clear_existing_rpe(tmp_path):
    state = State(tmp_path / 'state.db')
    api = API(.6)
    assert sync_one(Garmin(None), api, state, '1', '2') == 'missing'
    assert api.value == .6 and not api.patches


def test_non_activity_event_is_never_patched(tmp_path):
    state = State(tmp_path / 'state.db')
    class Training(API):
        def metric_request(self, method, path, **kwargs):
            assert method == 'GET'
            return {'type': 'TRAINING', 'rpe': None}
    with pytest.raises(ValueError, match='Unexpected OpenAthlete event'):
        sync_one(Garmin(70), Training(), state, '1', '2')


def test_failed_patch_verification_keeps_backfill_retryable(tmp_path):
    state = State(tmp_path / 'state.db')
    state.add('1', '2', '2026-01-01')
    class FailedVerification(API):
        def metric_request(self, method, path, **kwargs):
            return {'type': 'ACTIVITY', 'rpe': None}
    with pytest.raises(RuntimeError, match='verification failed'):
        sync_one(Garmin(70), FailedVerification(), state, '1', '2')
    assert state.rpe_written('1', '2') is None
    assert state.rpe_backfill_candidates() == [('1', '2')]


def test_rate_limit_stops_scan_and_keeps_remaining_candidates(tmp_path, monkeypatch):
    import requests
    state = State(tmp_path / 'state.db')
    state.add('1', '2', '2026-01-01')
    state.add('3', '4', '2026-01-02')
    calls = []
    class Limited(Garmin):
        def get_activity(self, gid):
            calls.append(gid)
            response = requests.Response()
            response.status_code = 429
            raise requests.HTTPError(response=response)
    monkeypatch.setattr('app.rpe.time.sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='incomplete'):
        sync_rpe(None, Limited(70), API(), state, backfill=True)
    assert len(calls) == 1
    assert len(state.rpe_backfill_candidates()) == 2


def test_recent_window_and_older_rotation_do_not_duplicate_ids(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    state = State(tmp_path / 'state.db')
    for gid in ('1', '2', '3'):
        state.add(gid, gid, '2026-01-01')
    class Recent(Garmin):
        def recent(self, limit):
            return [dict(activityId='1', startTimeGMT=datetime.now(timezone.utc).isoformat()),
                    dict(activityId='2', startTimeGMT=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat())]
    seen = []
    monkeypatch.setattr('app.rpe.sync_one', lambda g, o, state, gid, oid: seen.append(gid) or 'unchanged')
    monkeypatch.setattr('app.rpe.time.sleep', lambda _: None)
    result = sync_rpe(SimpleNamespace(lookback_days=7, activity_limit=100), Recent(70), API(), state)
    assert result['unchanged'] == 3
    assert len(seen) == len(set(seen)) == 3
