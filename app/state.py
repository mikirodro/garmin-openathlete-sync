import sqlite3
from pathlib import Path

class State:
    def __init__(self,path:Path):
        self.db=sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS synced_activity (garmin_id TEXT PRIMARY KEY, openathlete_id TEXT, synced_at TEXT NOT NULL)")
        self.db.commit()
    def contains(self,gid): return self.db.execute("SELECT 1 FROM synced_activity WHERE garmin_id=?",(gid,)).fetchone() is not None
    def add(self,gid,oid,when):
        self.db.execute("INSERT OR REPLACE INTO synced_activity VALUES (?,?,?)",(gid,str(oid) if oid is not None else None,when)); self.db.commit()
