import sqlite3
from pathlib import Path

class State:
    def __init__(self,path:Path):
        self.db=sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS synced_activity (garmin_id TEXT PRIMARY KEY, openathlete_id TEXT, synced_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS synced_workout (garmin_schedule_id TEXT PRIMARY KEY, openathlete_id INTEGER NOT NULL, payload_hash TEXT NOT NULL, event_hash TEXT NOT NULL, synced_at TEXT NOT NULL)")
        self.db.commit()
    def contains(self,gid): return self.db.execute("SELECT 1 FROM synced_activity WHERE garmin_id=?",(gid,)).fetchone() is not None
    def add(self,gid,oid,when):
        self.db.execute("INSERT OR REPLACE INTO synced_activity VALUES (?,?,?)",(gid,str(oid) if oid is not None else None,when)); self.db.commit()

    def workout(self, schedule_id):
        row = self.db.execute("SELECT openathlete_id, payload_hash, event_hash FROM synced_workout WHERE garmin_schedule_id=?", (str(schedule_id),)).fetchone()
        return dict(zip(("event_id", "payload_hash", "event_hash"), row)) if row else None

    def save_workout(self, schedule_id, event_id, payload_hash, event_hash, when):
        self.db.execute("INSERT OR REPLACE INTO synced_workout VALUES (?,?,?,?,?)",
                        (str(schedule_id), event_id, payload_hash, event_hash, when))
        self.db.commit()
