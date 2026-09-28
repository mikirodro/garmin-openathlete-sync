from pathlib import Path

from garminconnect import ActivityDownloadFormat, Garmin

SPORT_MAP = {
    "running": "RUNNING",
    "trail_running": "TRAIL_RUNNING",
    "cycling": "CYCLING",
    "mountain_biking": "CYCLING",
    "swimming": "SWIMMING",
    "open_water_swimming": "SWIMMING",
    "walking": "WALK",
    "hiking": "HIKING",
    "strength_training": "STRENGTH",
}


def sport_for(activity):
    activity_type = activity.get("activityType") or {}
    key = (
        activity_type.get("typeKey")
        or activity_type.get("parentTypeKey")
        or ""
    ).lower()
    return SPORT_MAP.get(key, "OTHER")


class GarminClient:
    def __init__(self, email, password, token_dir: Path):
        token_dir.mkdir(parents=True, exist_ok=True)
        self.client = Garmin(email, password)
        self.token_dir = str(token_dir)

    def login(self):
        self.client.login(self.token_dir)

    def recent(self, limit):
        data = self.client.get_activities(0, limit)
        if isinstance(data, dict):
            return data.get("activityList", []) or []
        return data or []

    def download_tcx(self, activity_id, out):
        out.write_bytes(
            self.client.download_activity(
                activity_id, ActivityDownloadFormat.TCX
            )
        )
