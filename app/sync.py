import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from .config import Config
from .garmin import GarminClient
from .openathlete import OpenAthleteClient
from .state import State

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


def main():
    parser = argparse.ArgumentParser(description="Daily Garmin FIT import into OpenAthlete")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Sync once, exit nonzero on failures")
    mode.add_argument("--login", action="store_true", help="Initialize Garmin tokens with interactive MFA")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = Config.from_env()
    g = GarminClient(c.garmin_email, c.garmin_password, c.data_dir / "garmin", interactive=args.login)
    if args.login:
        g.login()
        log.info("Garmin tokens initialized")
        return
    state = State(c.data_dir / "state.sqlite3")
    o = OpenAthleteClient(c.openathlete_base_url, c.openathlete_email, c.openathlete_password)
    if args.once:
        log.info("Sync: %s activities", run_once(c, g, o, state))
        return
    while True:
        try:
            log.info("Sync: %s activities", run_once(c, g, o, state))
        except Exception as error:
            # Do not log HTTP response bodies or authentication secrets.
            log.error("Sync cycle failed (%s); see activity errors above", type(error).__name__)
        log.info("Next sync in %s seconds", c.sync_interval)
        time.sleep(c.sync_interval)
