"""Measured FTP history; no inferred VMA or critical power."""
import json
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean
from zoneinfo import ZoneInfo

from .health import SOURCE, number

log = logging.getLogger("sync.performance")
FTP_TYPES = {"RUNNING": "FTP_RUNNING", "CYCLING": "FTP_CYCLING"}


def ftp_records(response, sport, start, end):
    """Parse Garmin daily LATEST series without filling gaps or changing sports."""
    if sport not in FTP_TYPES:
        raise ValueError("Unsupported FTP sport")
    if response is None or response == {}:
        return []
    if not isinstance(response, list):
        raise ValueError("Unexpected Garmin FTP response")
    records = {}
    for record in response:
        if not isinstance(record, dict) or record.get("series") != sport.lower():
            raise ValueError("Unexpected Garmin FTP series")
        try:
            first = date.fromisoformat(record["from"])
            last = date.fromisoformat(record["until"])
            measured = date.fromisoformat(record["updatedDate"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Unexpected Garmin FTP date") from None
        if first != last:
            raise ValueError("Expected daily Garmin FTP record")
        if measured != first or not start <= measured <= end:
            continue
        value = record.get("value")
        if not number(value, 0.000001):
            continue
        day = measured.isoformat()
        if day in records and records[day] != value:
            raise ValueError("Conflicting Garmin FTP records for one day")
        records[day] = value
    return [{"date": day, "watts": value} for day, value in sorted(records.items())]


def sync_performance(c, g, o, days=None, end=None):
    """FTP only, in <=366-day requests, using same-day weight for running W/kg."""
    days = days if days is not None else c.health_lookback_days
    if days < 1:
        raise ValueError("Performance days must be positive")
    end = end or (datetime.now(ZoneInfo(os.getenv("TZ", "Europe/Madrid"))).date() - timedelta(days=1))
    start = end - timedelta(days=days - 1)
    existing = {(m["date"][:10], m["type"]): m for m in o.metrics()}
    report = {"start": start.isoformat(), "end": end.isoformat(), "written": 0,
              "unchanged": 0, "preserved_manual": 0, "failures": 0, "types": {},
              "available": {kind: 0 for kind in FTP_TYPES.values()},
              "missing_running_weight": 0,
              "unsupported": ["VMA", "CRITICAL_POWER_RUNNING", "CRITICAL_POWER_CYCLING"]}
    # Most recent data first; range requests never exceed Garmin's 366-day limit.
    batch_end = end
    while batch_end >= start:
        batch_start = max(start, batch_end - timedelta(days=365))
        for sport, kind in FTP_TYPES.items():
            try:
                response = g.client.get_functional_threshold_power_range(
                    batch_start.isoformat(), batch_end.isoformat(), sport=sport, aggregation="daily")
                records = ftp_records(response, sport, batch_start, batch_end)
                report["available"][kind] += len(records)
            except Exception as error:
                log.error("FTP %s fetch failed (%s)", sport, type(error).__name__)
                report["failures"] += 1
                continue
            finally:
                time.sleep(.3)
            weights = defaultdict(list)
            if sport == "RUNNING" and records:
                try:
                    composition = g.client.get_body_composition(batch_start.isoformat(), batch_end.isoformat()) or {}
                    for entry in composition.get("dateWeightList") or []:
                        if number(entry.get("weight"), 0.000001):
                            weights[entry.get("calendarDate")].append(entry["weight"] / 1000)
                except Exception as error:
                    log.error("FTP running weight fetch failed (%s)", type(error).__name__)
                    report["failures"] += 1
            for record in records:
                day = record["date"]
                key = (day, kind)
                old = existing.get(key)
                if old and not (old.get("notes") or "").startswith(SOURCE):
                    report["preserved_manual"] += 1
                    continue
                value = record["watts"]
                notes = SOURCE + "; Garmin daily FTP; measured date; "
                if sport == "RUNNING":
                    weight_metric = existing.get((day, "WEIGHT")) or {}
                    if weights[day]:
                        mass = fmean(weights[day])
                        notes += "W/kg using same-day Garmin mean body weight"
                    elif number(weight_metric.get("value"), 0.000001):
                        mass = weight_metric["value"]
                        notes += "W/kg using same-day OpenAthlete body weight"
                    else:
                        report["missing_running_weight"] += 1
                        continue
                    value /= mass
                else:
                    notes += "W"
                if not number(value, 0.000001):
                    continue
                metric = {"type": kind, "date": day, "value": round(value, 6), "notes": notes}
                if old and abs(old["value"] - metric["value"]) < 0.000001:
                    report["unchanged"] += 1
                    continue
                try:
                    saved = o.upsert_metric(metric)
                    if saved.get("type") != kind or saved.get("date", "")[:10] != day:
                        raise ValueError("Unexpected metric response")
                    existing[key] = saved
                    report["written"] += 1
                    report["types"][kind] = report["types"].get(kind, 0) + 1
                except Exception as error:
                    log.error("FTP %s import failed (%s)", kind, type(error).__name__)
                    report["failures"] += 1
        log.info("FTP block %s..%s: cumulative written=%s failures=%s",
                 batch_start, batch_end, report["written"], report["failures"])
        batch_end = batch_start - timedelta(days=1)
    directory = c.data_dir / "performance"
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / "last-report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)
    if report["failures"]:
        raise RuntimeError(f"Performance sync had {report['failures']} failures; see performance report")
    return report
