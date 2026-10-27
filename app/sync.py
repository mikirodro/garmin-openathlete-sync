import argparse
import logging
import time
from datetime import date, datetime, timedelta, timezone

from .config import Config
from .garmin import GarminClient
from .openathlete import OpenAthleteClient
from .state import State
from .health import sync_health
from .performance import sync_performance
from .planned import sync_planned

log = logging.getLogger("sync")


def dt(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def run_once(c, g, o, state):
    g.login()
    o.login()
    cutoff = datetime.now(timezone.utc) - timedelta(days=c.lookback_days)
    folder = c.data_dir / "activities"
    folder.mkdir(parents=True, exist_ok=True)
    imported = failed = 0
    attempted = set()

    def upload(gid, path, name):
        nonlocal imported, failed
        attempted.add(gid)
        try:
            result = o.import_fit(path, name)
            if not result.get("eventId"):
                raise ValueError("OpenAthlete response has no eventId")
            if result.get("processingQueued") is False:
                raise RuntimeError("Activity saved, but processing not queued; retry next cycle")
            state.add(gid, result["eventId"], datetime.now(timezone.utc).isoformat())
            imported += 1
            log.info("Imported Garmin %s -> OpenAthlete %s", gid, result["eventId"])
            if result.get("warnings"):
                log.warning("Garmin %s import warnings: %s", gid, result["warnings"])
        except Exception as error:
            failed += 1
            log.error("FIT import failed for Garmin %s (%s)", gid, type(error).__name__)

    # Archived failed uploads remain retryable even after the lookback window.
    for path in sorted(folder.glob("*.fit")):
        if path.stem.isdecimal() and not state.contains(path.stem):
            name_file = path.with_suffix(".name.txt")
            name = name_file.read_text(encoding="utf-8") if name_file.exists() else "Garmin " + path.stem
            upload(path.stem, path, name)

    for activity in g.recent(c.activity_limit):
        gid = str(activity.get("activityId", ""))
        try:
            # Garmin lists newest first. Use GMT, never interpret local time as UTC.
            start = dt(activity["startTimeGMT"])
            if start < cutoff:
                break
            if not gid.isdecimal() or state.contains(gid) or gid in attempted:
                continue
            path = folder / (gid + ".fit")
            name = (str(activity.get("activityName") or "Garmin " + gid).strip() or "Garmin " + gid)[:100]
            g.download_fit(gid, path)
            path.with_suffix(".name.txt").write_text(name, encoding="utf-8")
        except Exception as error:
            failed += 1
            log.error("FIT download failed for Garmin %s (%s)", gid, type(error).__name__)
            continue
        upload(gid, path, name)
    if failed:
        raise RuntimeError(f"{failed} activities failed; {imported} imported; failures will be retried")
    return imported


def run_cycle(c, g, o, state, health_days=None, health_only=False, planned_days=None):
    failures = []
    if health_only:
        g.login()
        o.login()
    else:
        try:
            log.info("Sync: %s activities", run_once(c, g, o, state))
        except Exception as error:
            failures.append(error)
            log.error("Activity cycle failed (%s)", type(error).__name__)
    try:
        if g.client is None:
            g.login()
        log.info("Health summary: %s", sync_health(c, g, o, days=health_days))
    except Exception as error:
        failures.append(error)
        log.error("Health cycle failed (%s)", type(error).__name__)
    try:
        if g.client is None:
            g.login()
        log.info("Performance summary: %s", sync_performance(c, g, o, days=health_days))
    except Exception as error:
        failures.append(error)
        log.error("Performance cycle failed (%s)", type(error).__name__)
    if not health_only:
        try:
            if g.client is None:
                g.login()
            sync_planned(c, g, o, state, days=planned_days)
        except Exception as error:
            failures.append(error)
            log.error("Scheduled workout cycle failed (%s)", type(error).__name__)
    if failures:
        raise RuntimeError(f"{len(failures)} sync stages failed")


def main():
    parser = argparse.ArgumentParser(description="Garmin activities, health and scheduled workouts into OpenAthlete")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Sync once, exit nonzero on failures")
    mode.add_argument("--login", action="store_true", help="Initialize Garmin tokens with interactive MFA")
    mode.add_argument("--health-only", action="store_true", help="Import health once without activities")
    mode.add_argument("--performance-only", action="store_true", help="Import FTP history only; window from --health-days")
    mode.add_argument("--planned-only", action="store_true", help="Import scheduled workouts once")
    parser.add_argument("--health-days", type=int, help="Completed calendar days of health history")
    parser.add_argument("--planned-days", type=int, help="Upcoming calendar days of scheduled workouts (1..366)")
    parser.add_argument("--planned-start", type=date.fromisoformat, help="First calendar date, YYYY-MM-DD (with --planned-only)")
    parser.add_argument("--planned-end", type=date.fromisoformat, help="Last calendar date, YYYY-MM-DD (inclusive)")
    args = parser.parse_args()
    if args.health_days is not None and args.health_days <= 0:
        parser.error("--health-days must be positive")
    if args.planned_days is not None and not 1 <= args.planned_days <= 366:
        parser.error("--planned-days must be 1..366")
    if args.planned_start is not None or args.planned_end is not None:
        if not args.planned_only or args.planned_start is None or args.planned_end is None:
            parser.error("--planned-start and --planned-end require each other and --planned-only")
        if args.planned_days is not None:
            parser.error("Use a date range or --planned-days, not both")
        if not 0 <= (args.planned_end - args.planned_start).days < 366:
            parser.error("Planned date range must contain 1..366 days")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = Config.from_env()
    g = GarminClient(c.garmin_email, c.garmin_password, c.data_dir / "garmin", interactive=args.login)
    if args.login:
        g.login()
        log.info("Garmin tokens initialized")
        return
    o = OpenAthleteClient(c.openathlete_base_url, c.openathlete_email, c.openathlete_password)
    if args.performance_only:
        g.login()
        o.login()
        sync_performance(c, g, o, days=args.health_days)
        return
    state = State(c.data_dir / "state.sqlite3")
    if args.planned_only:
        g.login()
        o.login()
        sync_planned(c, g, o, state, days=args.planned_days,
                     start_date=args.planned_start, end_date=args.planned_end)
        return
    if args.once or args.health_only:
        run_cycle(c, g, o, state, args.health_days, args.health_only, args.planned_days)
        return
    while True:
        try:
            run_cycle(c, g, o, state, args.health_days, planned_days=args.planned_days)
        except Exception as error:
            # Do not log HTTP response bodies or authentication secrets.
            log.error("Sync cycle failed (%s); see activity errors above", type(error).__name__)
        log.info("Next sync in %s seconds", c.sync_interval)
        time.sleep(c.sync_interval)
