import os
from dataclasses import dataclass
from pathlib import Path

def secret(name):
    path=os.getenv(name+"_FILE")
    return Path(path).read_text(encoding="utf-8").strip() if path else os.getenv(name,"")

@dataclass(frozen=True)
class Config:
    garmin_email:str; garmin_password:str; openathlete_base_url:str
    openathlete_email:str; openathlete_password:str; sync_interval:int
    activity_limit:int; lookback_days:int; data_dir:Path

    @classmethod
    def from_env(cls):
        data=Path(os.getenv("DATA_DIR","/data"))
        c=cls(os.getenv("GARMIN_EMAIL",""),secret("GARMIN_PASSWORD"),
              os.getenv("OPENATHLETE_BASE_URL", "http://api:3000").rstrip("/"),
              os.getenv("OPENATHLETE_EMAIL",""),secret("OPENATHLETE_PASSWORD"),
              int(os.getenv("SYNC_INTERVAL_SECONDS","900")),
              int(os.getenv("GARMIN_ACTIVITY_LIMIT","20")),
              int(os.getenv("GARMIN_ACTIVITY_LOOKBACK_DAYS","7")),data)
        missing=[k for k,v in {"GARMIN_EMAIL":c.garmin_email,"GARMIN_PASSWORD":c.garmin_password,
          "OPENATHLETE_BASE_URL":c.openathlete_base_url,"OPENATHLETE_EMAIL":c.openathlete_email,
          "OPENATHLETE_PASSWORD":c.openathlete_password}.items() if not v]
        if missing: raise ValueError("Missing configuration: "+", ".join(missing))
        data.mkdir(parents=True,exist_ok=True)
        return c
