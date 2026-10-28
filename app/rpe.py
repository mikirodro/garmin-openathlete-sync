"""Synchronize Garmin self-evaluations without overwriting manual edits."""
import logging
import math
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger('sync.rpe')


def normalize(raw):
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not 0 <= raw <= 100:
        raise ValueError('Invalid Garmin RPE')
    return raw / 100


def equal(a, b):
    return a is not None and b is not None and abs(a - b) < 1e-8


def sync_one(g, o, state, gid, event_id):
    details = g.client.get_activity(gid)
    raw = (details.get('summaryDTO') or {}).get('directWorkoutRpe')
    desired = normalize(raw)
    if desired is None:
        state.mark_rpe_checked(gid)
        return 'missing'
    event = o.metric_request('GET', f'/event/{event_id}')
    if event.get('type') != 'ACTIVITY' or 'rpe' not in event:
        raise ValueError('Unexpected OpenAthlete event')
    current = event['rpe']
    last = state.rpe_written(gid, event_id)
    if state.rpe_manual(gid, event_id):
        state.mark_rpe_checked(gid)
        return 'preserved_manual'
    if current is not None and (last is None or not equal(current, last)):
        state.lock_rpe_manual(gid, event_id)
        return 'unchanged' if equal(current, desired) else 'preserved_manual'
    if equal(current, desired):
        state.mark_rpe_checked(gid)
        return 'unchanged'
    if current is None and last is not None:
        state.lock_rpe_manual(gid, event_id)
        return 'preserved_manual'
    o.metric_request('PATCH', f'/event/{event_id}', json={'type': 'ACTIVITY', 'rpe': desired})
    verified = o.metric_request('GET', f'/event/{event_id}')
    if not equal(verified.get('rpe'), desired):
        raise RuntimeError('RPE verification failed')
    state.save_rpe_written(gid, event_id, desired)
    return 'written'


def sync_rpe(c, g, o, state, backfill=False):
    counts = {'written': 0, 'unchanged': 0, 'missing': 0, 'preserved_manual': 0, 'failed': 0}
    if backfill:
        rows = state.rpe_backfill_candidates()
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=c.lookback_days)
        recent = []
        for activity in g.recent(c.activity_limit):
            start = datetime.fromisoformat(str(activity['startTimeGMT']).replace('Z', '+00:00'))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if start < cutoff:
                break
            gid = str(activity.get('activityId', ''))
            oid = state.activity_event(gid)
            if oid:
                recent.append((gid, oid))
        seen = {gid for gid, _ in recent}
        rows = recent + [(gid, oid) for gid, oid in state.rpe_oldest_candidates(20) if gid not in seen]
    for gid, oid in rows:
        try:
            counts[sync_one(g, o, state, gid, oid)] += 1
        except Exception as error:
            counts['failed'] += 1
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            log.warning('RPE sync failed for Garmin %s (%s, HTTP %s)', gid, type(error).__name__, status)
            if status == 429 or 'TooManyRequests' in type(error).__name__:
                log.error('Stopping RPE scan due to rate limit; remaining activities can be retried')
                break
        time.sleep(0.25)
    log.info('RPE summary: %s', counts)
    if counts['failed']:
        raise RuntimeError('RPE sync incomplete')
    return counts
