import sqlite3
from pathlib import Path

class State:
    def __init__(self,path:Path):
        self.db=sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS synced_activity (garmin_id TEXT PRIMARY KEY, openathlete_id TEXT, synced_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS synced_workout (garmin_schedule_id TEXT PRIMARY KEY, openathlete_id INTEGER NOT NULL, payload_hash TEXT NOT NULL, event_hash TEXT NOT NULL, synced_at TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS rejected_activity (garmin_id TEXT PRIMARY KEY, code TEXT NOT NULL, rejected_at TEXT NOT NULL)")
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

    def activity_event(self, gid):
        row = self.db.execute('SELECT openathlete_id FROM synced_activity WHERE garmin_id=?', (gid,)).fetchone()
        return row[0] if row and row[0] else None

    def ensure_rpe(self):
        self.db.execute('CREATE TABLE IF NOT EXISTS synced_rpe (garmin_id TEXT PRIMARY KEY, event_id TEXT, last_written REAL, checked_at TEXT)')
        self.db.commit()

    def rpe_written(self, gid, event_id):
        self.ensure_rpe()
        row = self.db.execute('SELECT last_written FROM synced_rpe WHERE garmin_id=? AND event_id=?', (gid, str(event_id))).fetchone()
        return row[0] if row else None

    def mark_rpe_checked(self, gid):
        self.ensure_rpe()
        self.db.execute("INSERT INTO synced_rpe (garmin_id,checked_at) VALUES (?,datetime('now')) ON CONFLICT(garmin_id) DO UPDATE SET checked_at=excluded.checked_at", (gid,))
        self.db.commit()

    def save_rpe_written(self, gid, event_id, value):
        self.ensure_rpe()
        self.db.execute("INSERT INTO synced_rpe VALUES (?,?,?,datetime('now')) ON CONFLICT(garmin_id) DO UPDATE SET event_id=excluded.event_id,last_written=excluded.last_written,checked_at=excluded.checked_at", (gid, str(event_id), value))
        self.db.commit()

    def rpe_backfill_candidates(self):
        self.ensure_rpe()
        return self.db.execute('SELECT a.garmin_id,a.openathlete_id FROM synced_activity a LEFT JOIN synced_rpe r ON r.garmin_id=a.garmin_id WHERE a.openathlete_id IS NOT NULL AND r.checked_at IS NULL ORDER BY a.synced_at DESC').fetchall()

    def rpe_oldest_candidates(self, limit):
        self.ensure_rpe()
        return self.db.execute('SELECT a.garmin_id,a.openathlete_id FROM synced_activity a LEFT JOIN synced_rpe r ON r.garmin_id=a.garmin_id WHERE a.openathlete_id IS NOT NULL ORDER BY COALESCE(r.checked_at,\'\'),a.synced_at DESC LIMIT ?', (limit,)).fetchall()

    def rpe_manual(self, gid, event_id):
        self.db.execute("CREATE TABLE IF NOT EXISTS rpe_manual_lock (garmin_id TEXT PRIMARY KEY, event_id TEXT NOT NULL)")
        return self.db.execute("SELECT 1 FROM rpe_manual_lock WHERE garmin_id=? AND event_id=?", (gid, str(event_id))).fetchone() is not None

    def lock_rpe_manual(self, gid, event_id):
        self.db.execute("CREATE TABLE IF NOT EXISTS rpe_manual_lock (garmin_id TEXT PRIMARY KEY, event_id TEXT NOT NULL)")
        self.db.execute("INSERT OR REPLACE INTO rpe_manual_lock VALUES (?,?)", (gid, str(event_id)))
        self.db.commit()
        self.mark_rpe_checked(gid)

    def rejected(self, gid):
        return self.db.execute("SELECT 1 FROM rejected_activity WHERE garmin_id=?", (gid,)).fetchone() is not None

    def reject(self, gid, code, when):
        self.db.execute("INSERT OR REPLACE INTO rejected_activity VALUES (?,?,?)", (gid, code, when))
        self.db.commit()

    def clear_rejected(self):
        ids = [row[0] for row in self.db.execute("SELECT garmin_id FROM rejected_activity")]
        self.db.execute("DELETE FROM rejected_activity")
        self.db.commit()
        return ids
