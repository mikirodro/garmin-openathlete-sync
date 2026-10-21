"""Daily Garmin health summaries -> OpenAthlete, without FIT imports."""
import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import fmean
from zoneinfo import ZoneInfo
import os

log = logging.getLogger("sync.health")
SOURCE = "Garmin Connect daily sync v1"


def number(value, minimum=0):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= minimum)


def daily_metrics(day, stats, heart, hrv, sleep, weights, respiration=None):
    """Means for repeated measurements; preserve named totals/extrema/summaries."""
    values = {}
    def put(kind, value, scale=1, minimum=0):
        if number(value, minimum):
            values[kind] = round(value * scale, 6)

    for kind, key in {
        "DAILY_CALORIES": "totalKilocalories", "DAILY_ACTIVE_CALORIES": "activeKilocalories",
        "DAILY_BMR_CALORIES": "bmrKilocalories", "DAILY_STEPS": "totalSteps",
        "DAILY_MODERATE_MINUTES": "moderateIntensityMinutes",
        "DAILY_VIGOROUS_MINUTES": "vigorousIntensityMinutes", "DAILY_FLOORS": "floorsAscended",
        "STRESS_AVERAGE": "averageStressLevel", "STRESS_MAX": "maxStressLevel",
        "BODY_BATTERY_CHARGED": "bodyBatteryChargedValue",
        "BODY_BATTERY_DRAINED": "bodyBatteryDrainedValue",
    }.items():
        put(kind, stats.get(key))
    put("DAILY_DISTANCE", stats.get("totalDistanceMeters"), 1 / 1000)
    put("DAILY_ACTIVE_MINUTES", stats.get("activeSeconds"), 1 / 60)
    for kind, key in {
        "STRESS_DURATION": "stressDuration", "STRESS_REST_DURATION": "restStressDuration",
        "STRESS_ACTIVITY_DURATION": "activityStressDuration", "STRESS_LOW_DURATION": "lowStressDuration",
        "STRESS_MEDIUM_DURATION": "mediumStressDuration", "STRESS_HIGH_DURATION": "highStressDuration",
    }.items():
        put(kind, stats.get(key), 1 / 60)
    for kind, key in {"HR_REST": "restingHeartRate", "HR_MIN_DAILY": "minHeartRate",
                      "HR_MAX_DAILY": "maxHeartRate"}.items():
        put(kind, heart.get(key, stats.get(key)), minimum=1)
    readings = [r[1] for r in (heart.get("heartRateValues") or [])
                if isinstance(r, (list, tuple)) and len(r) > 1 and number(r[1], 1)]
    if readings:
        put("HR_AVG_DAILY", fmean(readings), minimum=1)
    summary = hrv.get("hrvSummary") or {}
    put("HRV_LAST_NIGHT_AVG", summary.get("lastNightAvg"), minimum=1)
    put("HRV_LAST_NIGHT_5MIN_HIGH", summary.get("lastNight5MinHigh"), minimum=1)
    sl = sleep.get("dailySleepDTO") or {}
    for kind, key in {
        "SLEEP_DURATION": "sleepTimeSeconds", "SLEEP_REM_DURATION": "remSleepSeconds",
        "SLEEP_DEEP_DURATION": "deepSleepSeconds", "SLEEP_LIGHT_DURATION": "lightSleepSeconds",
        "SLEEP_AWAKE_DURATION": "awakeSleepSeconds", "NAP_DURATION": "napTimeSeconds",
    }.items():
        put(kind, sl.get(key), 1 / 3600)
    put("SLEEP_SCORE", ((sl.get("sleepScores") or {}).get("overall") or {}).get("value"))
    for kind, value in {
        "SLEEP_RESPIRATION_AVG": sl.get("averageRespirationValue"),
        "SLEEP_SPO2_AVG": sl.get("averageSpO2Value"),
        "PULSE_OX_AVG": stats.get("averageSpo2"), "PULSE_OX_MIN": stats.get("lowestSpo2"),
    }.items():
        put(kind, value, minimum=1)
    respiration_samples = [r[1] for r in ((respiration or {}).get("respirationValuesArray") or [])
                           if isinstance(r, (list, tuple)) and len(r) > 1 and number(r[1], 0.000001)]
    if respiration_samples:
        put("RESPIRATION_RATE_AVG", fmean(respiration_samples), minimum=0.000001)
    for kind, (key, scale) in {
        "WEIGHT": ("weight", .001), "BMI": ("bmi", 1), "BODY_FAT": ("bodyFat", 1),
        "BODY_WATER": ("bodyWater", 1), "MUSCLE_MASS": ("muscleMass", .001),
        "BONE_MASS": ("boneMass", .001),
    }.items():
        samples = [w[key] for w in weights if number(w.get(key), 0.000001)]
        if samples:
            put(kind, fmean(samples), scale)
    return [{"type": kind, "date": day, "value": value,
             "notes": SOURCE + "; daily means for repeated measurements; Garmin totals/extrema and overnight summaries retained"}
            for kind, value in sorted(values.items())]


def sync_health(c, g, o, days=None, end=None):
    days = days if days is not None else c.health_lookback_days
    if days < 1:
        raise ValueError("Health days must be positive")
    # Completed local calendar days only; Garmin's calendarDate is authoritative.
    end = end or (datetime.now(ZoneInfo(os.getenv("TZ", "Europe/Madrid"))).date() - timedelta(days=1))
    start = end - timedelta(days=days - 1)
    existing = {(m["date"][:10], m["type"]): m for m in o.metrics()}
    weights = defaultdict(list)
    weight_error = False
    try:
        composition = g.client.get_body_composition(start.isoformat(), end.isoformat()) or {}
        for entry in composition.get("dateWeightList") or []:
            day = entry.get("calendarDate")
            if isinstance(day, str) and start.isoformat() <= day <= end.isoformat():
                weights[day].append(entry)
    except Exception as error:
        log.error("Body composition fetch failed (%s)", type(error).__name__)
        weight_error = True
    report = {"start": start.isoformat(), "end": end.isoformat(), "written": 0,
              "unchanged": 0, "preserved_manual": 0, "zero_not_supported": 0,
              "failures": int(weight_error), "types": {}}
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        responses = {}
        for method in ("get_stats", "get_heart_rates", "get_hrv_data", "get_sleep_data", "get_respiration_data"):
            try:
                responses[method] = getattr(g.client, method)(day) or {}
            except Exception as error:
                # Failed fetches are not replaced with zero values; next cycle retries.
                log.error("Health %s %s failed (%s)", day, method, type(error).__name__)
                responses[method] = {}
                report["failures"] += 1
            time.sleep(.3)
        metrics = daily_metrics(day, responses["get_stats"], responses["get_heart_rates"],
                                responses["get_hrv_data"], responses["get_sleep_data"], weights[day],
                                responses["get_respiration_data"])
        for metric in metrics:
            key = (day, metric["type"])
            old = existing.get(key)
            if old and not (old.get("notes") or "").startswith(SOURCE):
                report["preserved_manual"] += 1
                continue
            if old and abs(old["value"] - metric["value"]) < 0.000001:
                report["unchanged"] += 1
                continue
            if metric["value"] == 0 and not old:
                # v1.2.0 POST schema requires positive(); PATCH permits real zero.
                report["zero_not_supported"] += 1
                continue
            try:
                if metric["value"] == 0:
                    saved = o.metric_request("PATCH", "/metric/" + str(old["athleteMetricId"]),
                                             json={"value": 0, "notes": metric["notes"]})
                else:
                    saved = o.upsert_metric(metric)
                if saved.get("type") != metric["type"] or saved.get("date", "")[:10] != day:
                    raise ValueError("Unexpected metric response")
                existing[key] = saved
                report["written"] += 1
                report["types"][metric["type"]] = report["types"].get(metric["type"], 0) + 1
            except Exception as error:
                log.error("Health %s %s import failed (%s)", day, metric["type"], type(error).__name__)
                report["failures"] += 1
        log.info("Health %s: %s available metrics; cumulative written=%s failures=%s",
                 day, len(metrics), report["written"], report["failures"])
    directory = c.data_dir / "health"
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / "last-report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(target)
    if report["failures"]:
        raise RuntimeError(f"Health sync had {report['failures']} failures; see health logs")
    return report
