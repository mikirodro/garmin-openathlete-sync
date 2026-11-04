"""Read Garmin's calendar and import structured sessions into OpenAthlete."""
import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import date, datetime, time as day_time, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("sync.planned")
MARKER = "Referencia de calendario Garmin: "
SPORTS = {"running": "RUNNING", "trail_running": "TRAIL_RUNNING", "cycling": "CYCLING",
          "mountain_biking": "MOUNTAIN_BIKE_RIDE", "lap_swimming": "SWIMMING",
          "swimming": "SWIMMING", "strength_training": "STRENGTH", "cardio_training": "WORKOUT",
          "yoga": "YOGA", "pilates": "PILATES", "walking": "WALK", "hiking": "HIKING",
          "elliptical": "ELLIPTICAL", "rowing": "ROWING", "hiit": "HIGH_INTENSITY_INTERVAL_TRAINING"}


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def digest(value):
    def normalized(item):
        if isinstance(item, dict):
            return {k: normalized(v) for k, v in item.items()}
        if isinstance(item, list):
            return [normalized(v) for v in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def marker_id(event):
    match = re.search(r"(?:^|\n)" + re.escape(MARKER) + r"(\d+)(?:\n|$)", event.get("description") or "")
    return match[1] if match else None


def targets_for(step, sport, notes, warnings):
    targets = []
    for secondary in (False, True):
        prefix = "secondaryTarget" if secondary else "target"
        type_key = "secondaryTargetType" if secondary else "targetType"
        kind = (step.get(type_key) or {}).get("workoutTargetTypeKey")
        if not kind or kind in ("no.target", "open"):
            continue
        low, high = step.get(prefix + "ValueOne"), step.get(prefix + "ValueTwo")
        zone = step.get("secondaryZoneNumber" if secondary else "zoneNumber")
        if "heart.rate" in kind or kind in ("heart_rate", "heartrate"):
            target_type = "HEARTRATE"
        elif "power" in kind:
            target_type = "POWER"
        elif "pace" in kind or "speed" in kind:
            target_type = "PACE"  # Both APIs use m/s, not minutes/km.
        elif "cadence" in kind:
            target_type = "CADENCE"
        else:
            notes.append("Objetivo Garmin: " + json.dumps({"type": kind, "min": low, "max": high, "zone": zone}, ensure_ascii=False))
            warnings.add("target_in_notes:" + kind)
            continue
        if not positive(low) and not positive(high):
            if positive(zone):
                if target_type == "HEARTRATE":
                    targets.append({"targetType": "ZONE", "targetValue": zone})
                else:
                    notes.append(f"Objetivo Garmin: {kind}, zona {zone}")
                    warnings.add("zone_in_notes:" + kind)
            continue
        target = {"targetType": target_type}
        unit = step.get(prefix + "ValueUnit") or {}
        unit_key = unit.get("unitKey", "") if isinstance(unit, dict) else str(unit)
        scale = 1
        if "percent" in unit_key.lower() or "percent" in kind.lower():
            if target_type not in ("HEARTRATE", "POWER"):
                raise ValueError("Unsupported percentage target: " + kind)
            scale = .01
            target["metricType"] = "HR_MAX" if target_type == "HEARTRATE" else ("FTP_RUNNING" if sport == "RUNNING" else "FTP_CYCLING")
        if positive(low) and positive(high) and low != high:
            target.update(targetMin=round(min(low, high) * scale, 9), targetMax=round(max(low, high) * scale, 9))
        else:
            target["targetValue"] = round((low if positive(low) else high) * scale, 9)
        targets.append(target)
    weight = step.get("weightValue")
    if positive(weight):
        unit = (step.get("weightUnit") or {}).get("unitKey")
        if unit in ("kilogram", "kilograms", "kg", None):
            kg = weight
        elif unit in ("pound", "pounds", "lb"):
            kg = weight * .45359237
        else:
            notes.append(f"Peso Garmin: {weight} {unit}")
            warnings.add("weight_unit_in_notes:" + str(unit))
            kg = None
        if kg is not None:
            targets.append({"targetType": "WEIGHT", "targetValue": round(kg, 6)})
    return targets


def convert_steps(source, sport, warnings, depth=0):
    if depth > 5:
        raise ValueError("Garmin repeat nesting exceeds supported depth")
    result = []
    for step in sorted(source, key=lambda s: s.get("stepOrder", 0)):
        kind = (step.get("stepType") or {}).get("stepTypeKey", "interval")
        children = step.get("workoutSteps")
        if step.get("type") == "RepeatGroupDTO" or kind == "repeat":
            count = step.get("numberOfIterations", step.get("endConditionValue"))
            if not positive(count) or int(count) != count or not 1 <= count <= 99 or not children:
                raise ValueError("Unsupported Garmin repeat condition")
            mapped = convert_steps(children, sport, warnings, depth + 1)
            skip_rest = step.get("skipLastRestStep") and mapped[-1]["stepType"] == "INTERVAL_REST"
            if depth:
                # OpenAthlete permits one repeat level. Expand inner groups exactly.
                result.extend(mapped * int(count - bool(skip_rest)))
                if skip_rest:
                    result.extend(mapped[:-1])
            elif skip_rest:
                if count > 1:
                    result.append({"stepType": "REPEAT", "repeatBlock": {"repetitions": int(count) - 1, "childSteps": mapped}, "targets": []})
                result.extend(mapped[:-1])
            else:
                result.append({"stepType": "REPEAT", "repeatBlock": {"repetitions": int(count), "childSteps": mapped}, "targets": []})
        else:
            notes = [step["description"]] if step.get("description") else []
            for key in ("category", "exerciseName"):
                if step.get(key):
                    notes.append(str(step[key]))
            for key, subkey in (("strokeType", "strokeTypeKey"), ("equipmentType", "equipmentTypeKey")):
                if (step.get(key) or {}).get(subkey):
                    notes.append(str(step[key][subkey]))
            condition = (step.get("endCondition") or {}).get("conditionTypeKey", "lap.button")
            duration = {"time": "TIME", "distance": "DISTANCE", "calories": "CALORIES", "reps": "REPS",
                        "lap.button": "LAP_BUTTON", "open": "OPEN", "heart.rate.less.than": "HR_BELOW",
                        "heart.rate.greater.than": "HR_ABOVE"}.get(condition)
            if duration is None:
                notes.append(f"Fin de bloque Garmin: {condition}, valor {step.get('endConditionValue')}")
                warnings.add("duration_in_notes:" + condition)
                duration = "OPEN"
            mapped = {"stepType": {"warmup": "WARMUP", "cooldown": "COOLDOWN", "interval": "INTERVAL_ACTIVE",
                                   "rest": "INTERVAL_REST", "recovery": "INTERVAL_REST", "active": "STEADY"}.get(kind, "STEADY"),
                      "durationType": duration}
            if duration not in ("OPEN", "LAP_BUTTON"):
                if not positive(step.get("endConditionValue")):
                    raise ValueError("Missing Garmin duration")
                mapped["durationValue"] = step["endConditionValue"]
            mapped["targets"] = targets_for(step, sport, notes, warnings)
            if step.get("description") or step.get("exerciseName"):
                mapped["name"] = step.get("description") or step["exerciseName"]
            if notes:
                mapped["notes"] = "\n".join(notes)
            result.append(mapped)
        if len(result) > 1000:
            raise ValueError("Too many expanded workout steps")
    return result


def event_payload(item, workout, tz):
    sid = str(item["id"])
    if not sid.isdecimal():
        raise ValueError("Invalid Garmin calendar ID")
    sport_key = (workout.get("sportType") or {}).get("sportTypeKey") or item.get("sportTypeKey")
    sport = SPORTS.get(sport_key, "OTHER")
    warnings = set()
    if sport == "OTHER":
        warnings.add("sport:" + str(sport_key))
    steps = []
    for segment in sorted(workout.get("workoutSegments") or [], key=lambda s: s.get("segmentOrder", 0)):
        segment_sport = (segment.get("sportType") or {}).get("sportTypeKey", sport_key)
        if segment_sport != sport_key:
            raise ValueError("Mixed-sport segments need separate training events")
        steps.extend(convert_steps(segment.get("workoutSteps") or [], sport, warnings))
    if not steps:
        raise ValueError("Garmin workout has no steps")
    day = date.fromisoformat(item["date"][:10])
    start = datetime.combine(day, day_time.min, tzinfo=tz)
    clock = item.get("startTimestampLocal") or item.get("eventTimeLocal")
    if clock:
        if "T" in str(clock):
            start = datetime.fromisoformat(str(clock).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
        else:
            start = datetime.combine(day, day_time.fromisoformat(str(clock)), tzinfo=tz)
    duration = workout.get("estimatedDurationInSecs")
    distance = workout.get("estimatedDistanceInMeters")
    # No invented duration for LAP/reps sessions without a Garmin estimate.
    end = start + timedelta(seconds=duration if positive(duration) else 0)
    text = workout.get("description") or ""
    if warnings:
        text += "\nDetalles conservados en las notas de los bloques: " + ", ".join(sorted(warnings))
    text += f"\n\nGarmin Connect: https://connect.garmin.com/modern/workout/{item['workoutId']}\n{MARKER}{sid}"
    payload = {"type": "TRAINING", "name": (workout.get("workoutName") or item.get("title") or "Entrenamiento Garmin")[:100],
               "startDate": start.isoformat(), "endDate": end.isoformat(), "sport": sport,
               "description": text.strip(), "workout": {"steps": steps},
               "goalDuration": duration if positive(duration) else None,
               "goalDistance": distance if positive(distance) else None}
    return payload, sorted(warnings)


def event_content(event):
    """Ignore server IDs/estimates while detecting user edits to imported fields."""
    def step_content(step):
        result = {k: step.get(k) for k in ("stepType", "name", "notes", "durationType", "durationValue")}
        if result["durationType"] is None:
            result["durationType"] = "OPEN"
        result["targets"] = [{k: t.get(k) for k in ("targetType", "targetMin", "targetMax", "targetValue", "metricType")}
                             for t in step.get("targets") or []]
        repeat = step.get("repeatBlock")
        if repeat:
            result["repeatBlock"] = {"repetitions": repeat["repetitions"],
                                     "childSteps": [step_content(s) for s in repeat.get("childSteps") or []]}
        return result
    result = {k: event.get(k) for k in ("type", "name", "sport", "description", "goalDuration", "goalDistance")}
    for key in ("startDate", "endDate"):
        result[key] = datetime.fromisoformat(event[key].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    result["steps"] = [step_content(s) for s in (event.get("workout") or {}).get("steps") or []]
    return result


def sync_planned(c, g, o, state, days=None, today=None, start_date=None, end_date=None):
    days = days if days is not None else c.planned_days
    if not 1 <= days <= 366:
        raise ValueError("Planned horizon must be 1..366")
    tz = ZoneInfo(os.getenv("TZ", "Europe/Madrid"))
    today = today or datetime.now(tz).date()
    if (start_date is None) != (end_date is None):
        raise ValueError("Both planned start and end dates are required")
    start = start_date or today
    end = end_date or (start + timedelta(days=days - 1))
    if not 0 <= (end - start).days < 366:
        raise ValueError("Planned date range must contain 1..366 days")
    report = {"start": start.isoformat(), "end": end.isoformat(), "available": 0, "created": 0,
              "updated": 0, "unchanged": 0, "recovered": 0, "preserved_manual": 0,
              "preserved_deleted": 0, "preserved_completed": 0, "failures": 0, "warnings": {}}
    items = {}
    month = start.replace(day=1)
    while month <= end:
        try:
            calendar = g.client.get_scheduled_workouts(month.year, month.month)
            for item in calendar.get("calendarItems") or []:
                day = str(item.get("date", ""))[:10]
                if item.get("itemType") == "workout" and start.isoformat() <= day <= end.isoformat():
                    items[str(item["id"])] = item  # Adjacent months repeat boundary items.
        except Exception as error:
            log.error("Garmin calendar %s fetch failed (%s)", month.isoformat(), type(error).__name__)
            report["failures"] += 1
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        time.sleep(.3)
    report["available"] = len(items)
    # All events allow recovery of a previous create whose response was lost, even after a move.
    existing = o.metric_request("GET", "/event")
    by_id = {e["eventId"]: e for e in existing}
    by_source = {}
    for event in existing:
        sid = marker_id(event)
        if sid:
            by_source.setdefault(sid, []).append(event)
    definitions = {}
    for sid, item in sorted(items.items(), key=lambda pair: (pair[1]["date"], pair[0])):
        try:
            wid = item["workoutId"]
            if not wid:
                raise ValueError("Calendar item lacks workout ID")
            if wid not in definitions:
                definitions[wid] = g.client.get_workout_by_id(wid)
                time.sleep(.3)
            payload, warnings = event_payload(item, definitions[wid], tz)
            if warnings:
                report["warnings"][sid] = warnings
            payload_hash = digest(payload)
            previous = state.workout(sid)
            candidates = by_source.get(sid, [])
            if len(candidates) > 1:
                raise ValueError("Multiple OpenAthlete events have the same Garmin reference")
            event = by_id.get(previous["event_id"]) if previous else (candidates[0] if candidates else None)
            if previous and event is None:
                report["preserved_deleted"] += 1
                continue
            if event:
                if event.get("type") != "TRAINING" or marker_id(event) != sid:
                    report["preserved_manual"] += 1
                    continue
                if event.get("relatedActivity") or event.get("relatedActivityId"):
                    report["preserved_completed"] += 1
                    continue
                actual_hash = digest(event_content(event))
                if previous and actual_hash != previous["event_hash"]:
                    report["preserved_manual"] += 1
                    continue
                if not previous:
                    if actual_hash != digest(event_content(payload)):
                        report["preserved_manual"] += 1
                        continue
                    report["recovered"] += 1
                elif previous["payload_hash"] == payload_hash:
                    report["unchanged"] += 1
                    continue
                else:
                    event = o.metric_request("PATCH", "/event/" + str(event["eventId"]), json=payload)
                    report["updated"] += 1
            else:
                event = o.metric_request("POST", "/event", json=payload)
                report["created"] += 1
            if event.get("type") != "TRAINING" or marker_id(event) != sid or not event.get("workout"):
                raise ValueError("OpenAthlete did not return a complete imported training")
            state.save_workout(sid, event["eventId"], payload_hash, digest(event_content(event)), datetime.now(timezone.utc).isoformat())
            by_id[event["eventId"]] = event
            by_source[sid] = [event]
        except Exception as error:
            response = getattr(error, "response", None)
            log.error("Scheduled Garmin %s import failed (%s, HTTP %s)", sid, type(error).__name__,
                      response.status_code if response is not None else "n/a")
            report["failures"] += 1
    directory = c.data_dir / "workouts"
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / "last-report.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(target)
    log.info("Planned summary: %s", report)
    if report["failures"]:
        raise RuntimeError(f"{report['failures']} scheduled workouts/calendar requests failed")
    return report
