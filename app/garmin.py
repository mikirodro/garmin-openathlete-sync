from pathlib import Path
from garminconnect import Garmin, ActivityDownloadFormat

SPORT_MAP={"running":"RUNNING","trail_running":"TRAIL_RUNNING","cycling":"CYCLING","mountain_biking":"CYCLING","swimming":"SWIMMING","open_water_swimming":"SWIMMING","walking":"WALK","hiking":"HIKING","strength_training":"STRENGTH"}

def sport_for(a):
    t=a.get("activityType") or {}
    key=(t.get("typeKey") or t.get("parentTypeKey") or "").lower()
    return SPORT_MAP.get(key,"OTHER")

class GarminClient:
    def __init__(self,email,password,token_dir:Path):
        token_dir.mkdir(parents=True,exist_ok=True)
        self.client=Garmin(email,password); self.token_dir=str(token_dir)
    def login(self): self.client.login(self.token_dir)
    def recent(self,limit): return self.client.get_activities(0,limit) or []
    def download_tcx(self,activity_id,out):
        out.write_bytes(self.client.download_activity(activity_id,ActivityDownloadFormat.TCX))
