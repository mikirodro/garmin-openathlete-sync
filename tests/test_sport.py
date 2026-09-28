from app.garmin import sport_for
def test_running(): assert sport_for({"activityType":{"typeKey":"running"}})=="RUNNING"
def test_unknown(): assert sport_for({"activityType":{"typeKey":"unknown"}})=="OTHER"
