import logging,time
from datetime import datetime,timezone,timedelta
from .config import Config
from .garmin import GarminClient,sport_for
from .openathlete import OpenAthleteClient
from .state import State

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("sync")

def dt(value):
    x=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return x if x.tzinfo else x.replace(tzinfo=timezone.utc)

def run_once(c,g,o,state):
    g.login(); o.login()
    cutoff=datetime.now(timezone.utc)-timedelta(days=c.lookback_days)
    count=0
    for a in reversed(g.recent(c.activity_limit)):
        gid=str(a.get("activityId"))
        if not gid or gid=="None" or state.contains(gid): continue
        start=dt(a.get("startTimeLocal") or a.get("startTimeGMT"))
        if start.astimezone(timezone.utc)<cutoff: continue
        end=start+timedelta(seconds=float(a.get("duration") or 0))
        result=o.create_activity(a.get("activityName"),start,end,sport_for(a),
          "Imported from Garmin Connect.")
        folder=c.data_dir/"activities"; folder.mkdir(exist_ok=True)
        try: g.download_tcx(gid,folder/(gid+".tcx"))
        except Exception: log.exception("TCX download failed for %s",gid)
        oid=result.get("eventId") or result.get("id")
        state.add(gid,oid,datetime.now(timezone.utc).isoformat()); count+=1
        log.info("Imported Garmin %s -> OpenAthlete %s",gid,oid)
    return count

def main():
    c=Config.from_env(); state=State(c.data_dir/"state.sqlite3")
    g=GarminClient(c.garmin_email,c.garmin_password,c.data_dir/"garmin")
    o=OpenAthleteClient(c.openathlete_base_url,c.openathlete_email,c.openathlete_password)
    while True:
        try: log.info("Sync: %s new activities",run_once(c,g,o,state))
        except Exception: log.exception("Sync cycle failed")
        time.sleep(c.sync_interval)
