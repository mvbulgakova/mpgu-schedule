from bot.db.models import User, Schedule, Institute, ErrorReport


def test_user_model_has_required_fields():
    u = User(user_id=123456789, institute_id="biology", group_code="БИО40-БА2501")
    assert u.user_id == 123456789
    assert u.group_code == "БИО40-БА2501"


def test_error_report_model():
    r = ErrorReport(user_id=1, group_code="БИО40-БА2501", message="Неверный преподаватель")
    assert r.group_code == "БИО40-БА2501"


def test_schedule_model_stores_json():
    data = {"name": "БИО40-БА2501", "schedule": {"odd_week": {}, "even_week": {}}}
    s = Schedule(group_code="БИО40-БА2501", institute_id="biology", data=data)
    assert s.data["name"] == "БИО40-БА2501"
