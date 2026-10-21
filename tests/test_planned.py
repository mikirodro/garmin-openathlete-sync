from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.planned import convert_steps, digest, event_payload, sync_planned
from app.state import State


def step(kind="interval", condition="time", value=60, **kwargs):
    return {"type": "ExecutableStepDTO", "stepType": {"stepTypeKey": kind},
            "endCondition": {"conditionTypeKey": condition}, "endConditionValue": value,
            "targetType": {"workoutTargetTypeKey": "no.target"}, **kwargs}


def repeat(children, count=3, **kwargs):
    return {"type": "RepeatGroupDTO", "stepType": {"stepTypeKey": "repeat"},
            "numberOfIterations": count, "workoutSteps": children, **kwargs}


def workout():
    return {"workoutName": "Intervals", "sportType": {"sportTypeKey": "running"},
            "estimatedDurationInSecs": 600, "estimatedDistanceInMeters": 2000,
            "workoutSegments": [{"workoutSteps": [step(description="Warmup")]}]}


def item(sid=123, day="2026-10-31"):
    return {"id": sid, "workoutId": 99, "date": day, "itemType": "workout"}


def test_strength_reps_lap_weights_and_repeats():
    source = [repeat([step(condition="reps", value=8, description="Lunge", weightValue=12,
                           weightUnit={"unitKey": "kilogram"}), step("rest", "lap.button", None)])]
    mapped = convert_steps(source, "STRENGTH", set())[0]["repeatBlock"]
    assert mapped["repetitions"] == 3
    active, rest = mapped["childSteps"]
    assert active["durationType"] == "REPS" and active["durationValue"] == 8
    assert active["targets"] == [{"targetType": "WEIGHT", "targetValue": 12}]
    assert rest["durationType"] == "LAP_BUTTON" and "durationValue" not in rest


def test_content_hash_ignores_json_integer_float_serialization():
    assert digest({"targets": [180.0, .8]}) == digest({"targets": [180, .8]})


def test_pace_power_secondary_hr_percent_and_zone_targets():
    pace = step(targetType={"workoutTargetTypeKey": "pace.zone"}, targetValueOne=2.8, targetValueTwo=3.3)
    power = step(targetType={"workoutTargetTypeKey": "power.3s"}, targetValueOne=180, targetValueTwo=220,
                 secondaryTargetType={"workoutTargetTypeKey": "cadence"}, secondaryTargetValueOne=80, secondaryTargetValueTwo=90)
    heart = step(targetType={"workoutTargetTypeKey": "heart.rate.zone"}, targetValueOne=70, targetValueTwo=80,
                 targetValueUnit={"unitKey": "percent"})
    zone = step(targetType={"workoutTargetTypeKey": "heart.rate.zone"}, zoneNumber=2)
    mapped = convert_steps([pace, power, heart, zone], "CYCLING", set())
    assert mapped[0]["targets"] == [{"targetType": "PACE", "targetMin": 2.8, "targetMax": 3.3}]
    assert mapped[1]["targets"][0] == {"targetType": "POWER", "targetMin": 180, "targetMax": 220}
    assert mapped[1]["targets"][1]["targetType"] == "CADENCE"
    assert mapped[2]["targets"][0] == {"targetType": "HEARTRATE", "metricType": "HR_MAX", "targetMin": .7, "targetMax": .8}
    assert mapped[3]["targets"] == [{"targetType": "ZONE", "targetValue": 2}]


def test_nested_repeats_expand_inner_and_skip_final_rest():
    nested = repeat([repeat([step(), step("rest")], count=2, skipLastRestStep=True)], count=3)
    mapped = convert_steps([nested], "RUNNING", set())[0]["repeatBlock"]
    assert mapped["repetitions"] == 3
    assert [s["stepType"] for s in mapped["childSteps"]] == ["INTERVAL_ACTIVE", "INTERVAL_REST", "INTERVAL_ACTIVE"]
    skipped = convert_steps([repeat([step(), step("rest")], count=3, skipLastRestStep=True)], "RUNNING", set())
    assert skipped[0]["repeatBlock"]["repetitions"] == 2
    assert skipped[-1]["stepType"] == "INTERVAL_ACTIVE"


def test_unknown_details_retained_in_notes_and_unknown_duration_not_invented():
    warnings = set()
    mapped = convert_steps([step(condition="mystery", value=42, targetType={"workoutTargetTypeKey": "grade"}, targetValueOne=5)], "RUNNING", warnings)[0]
    assert mapped["durationType"] == "OPEN" and "durationValue" not in mapped
    assert "mystery" in mapped["notes"] and "grade" in mapped["notes"]
    assert len(warnings) == 2


def test_calendar_timezone_dst_and_unknown_total_duration():
    w = workout()
    first, _ = event_payload(item(day="2026-10-24"), w, ZoneInfo("Europe/Madrid"))
    second, _ = event_payload(item(day="2026-10-26"), w, ZoneInfo("Europe/Madrid"))
    assert first["startDate"].endswith("+02:00") and second["startDate"].endswith("+01:00")
    assert second["goalDistance"] == 2000 and second["goalDuration"] == 600
    w["estimatedDurationInSecs"] = None
    unknown, _ = event_payload(item(), w, ZoneInfo("Europe/Madrid"))
    assert unknown["endDate"] == unknown["startDate"] and unknown["goalDuration"] is None


class Garmin:
    def __init__(self):
        self.items = [item()]
        self.definition = workout()
        self.reads = 0
    def get_scheduled_workouts(self, year, month):
        return {"calendarItems": self.items + [item(sid=1, day="2020-01-01")]}
    def get_workout_by_id(self, wid):
        self.reads += 1
        return self.definition


class API:
    def __init__(self):
        self.rows = []
        self.creates = self.updates = 0
        self.lose_response = False
    def metric_request(self, method, path, **kwargs):
        if method == "GET":
            return deepcopy(self.rows)
        payload = deepcopy(kwargs["json"])
        if method == "POST":
            self.creates += 1
            payload["eventId"] = self.creates
            self.rows.append(payload)
            if self.lose_response:
                self.lose_response = False
                raise TimeoutError("Response lost after commit")
        else:
            self.updates += 1
            payload["eventId"] = int(path.split("/")[-1])
            self.rows = [r for r in self.rows if r["eventId"] != payload["eventId"]] + [payload]
        return deepcopy(payload)


def setup_sync(tmp_path, monkeypatch):
    monkeypatch.setattr("app.planned.time.sleep", lambda _: None)
    c = SimpleNamespace(planned_days=45, data_dir=tmp_path)
    g, api = SimpleNamespace(client=Garmin()), API()
    state = State(tmp_path / "state.sqlite3")
    return c, g, api, state


def run(c, g, api, state):
    return sync_planned(c, g, api, state, today=date(2026, 10, 21))


def test_deduplicates_month_boundaries_and_same_template_on_two_dates(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    g.client.items.append(item(sid=124, day="2026-11-01"))
    report = run(c, g, api, state)
    assert report["created"] == report["available"] == 2
    assert g.client.reads == 1 and len(api.rows) == 2
    assert run(c, g, api, state)["unchanged"] == 2
    assert api.creates == 2 and api.updates == 0


def test_updates_changed_workout_and_rescheduled_date(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    run(c, g, api, state)
    g.client.items[0]["date"] = "2026-11-02"
    g.client.definition["workoutName"] = "Updated intervals"
    assert run(c, g, api, state)["updated"] == 1
    assert len(api.rows) == 1 and api.rows[0]["name"] == "Updated intervals"
    assert api.rows[0]["startDate"].startswith("2026-11-02")


def test_preserves_manual_changes_and_intentionally_deleted_sessions(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    run(c, g, api, state)
    api.rows[0]["name"] = "Edited in OpenAthlete"
    g.client.definition["workoutName"] = "Changed in Garmin"
    assert run(c, g, api, state)["preserved_manual"] == 1
    assert api.rows[0]["name"] == "Edited in OpenAthlete" and api.updates == 0
    api.rows.clear()
    assert run(c, g, api, state)["preserved_deleted"] == 1 and api.creates == 1


def test_recovers_lost_creation_response_without_duplicate(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    api.lose_response = True
    with pytest.raises(RuntimeError, match="1 scheduled"):
        run(c, g, api, state)
    assert state.workout(123) is None and len(api.rows) == 1
    assert run(c, g, api, state)["recovered"] == 1
    assert api.creates == 1 and state.workout(123)["event_id"] == 1


def test_calendar_failure_does_not_delete_existing_sessions(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    run(c, g, api, state)
    def fail(*args):
        raise RuntimeError("Garmin unavailable")
    g.client.get_scheduled_workouts = fail
    with pytest.raises(RuntimeError):
        run(c, g, api, state)
    assert len(api.rows) == 1 and api.updates == 0


def test_completed_sessions_are_not_overwritten(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    run(c, g, api, state)
    api.rows[0]["relatedActivityId"] = 42
    g.client.definition["workoutName"] = "Updated"
    assert run(c, g, api, state)["preserved_completed"] == 1
    assert api.updates == 0


def test_historical_range_is_inclusive_and_excludes_other_dates(tmp_path, monkeypatch):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    g.client.items = [item(sid=1, day="2026-09-20"), item(sid=2, day="2026-09-21"),
                      item(sid=3, day="2026-10-20"), item(sid=4, day="2026-10-21")]
    report = sync_planned(c, g, api, state, today=date(2026, 10, 21),
                          start_date=date(2026, 9, 21), end_date=date(2026, 10, 20))
    assert report["start"] == "2026-09-21" and report["end"] == "2026-10-20"
    assert report["available"] == report["created"] == 2
    assert {r["startDate"][:10] for r in api.rows} == {"2026-09-21", "2026-10-20"}
    repeated = sync_planned(c, g, api, state, start_date=date(2026, 9, 21), end_date=date(2026, 10, 20))
    assert repeated["unchanged"] == 2 and api.creates == 2


@pytest.mark.parametrize("start,end", [(date(2026,10,21), None),
    (date(2026,10,21), date(2026,10,20)), (date(2026,1,1),date(2027,1,2))])
def test_invalid_historical_range_is_rejected(tmp_path, monkeypatch, start, end):
    c, g, api, state = setup_sync(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        sync_planned(c, g, api, state, start_date=start, end_date=end)
    assert api.creates == 0
