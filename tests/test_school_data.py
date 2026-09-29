"""Unit tests for school_data (assignments, calendar, PE and lunch helpers). No HA needed."""

import sys
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "infomentor"))

import school_data  # noqa: E402


def _lesson(title, start, subject=None):
	return SimpleNamespace(title=title, subject=subject or title, start_time=start)


def _day(day, *lessons):
	return SimpleNamespace(date=datetime.combine(day, time()), timetable_entries=list(lessons))


def test_is_pe_matches_swedish_abbreviations_only_as_words():
	assert school_data.is_pe("Idh")
	assert school_data.is_pe("Ma", "Idrott och hälsa")
	assert school_data.is_pe("Gympa")
	assert not school_data.is_pe("Idhistoria")
	assert not school_data.is_pe("Ombyte", None)


def test_next_school_day_skips_today_and_days_without_lessons():
	today = date(2026, 9, 29)
	schedule = [
		_day(date(2026, 9, 29), _lesson("Idh", time(9))),
		_day(date(2026, 10, 1), _lesson("Sv", time(8))),
		_day(date(2026, 9, 30)),  # e.g. only fritids time registrations
	]
	assert school_data.next_school_day(schedule, today).date.date() == date(2026, 10, 1)
	assert school_data.next_school_day(schedule, date(2026, 10, 1)) is None


def test_pe_lessons_sorted_and_filtered():
	day = _day(date(2026, 10, 1), _lesson("Idh", time(13)), _lesson("Ma", time(8)), _lesson("Idh", time(9)))
	assert [entry.start_time for entry in school_data.pe_lessons(day)] == [time(9), time(13)]
	assert school_data.pe_lessons(None) == []


def test_normalize_tasks_and_due_filter():
	payload = {
		"items": [
			{"id": 1, "title": " Läsläxa ", "subject": "Sv", "dueDate": "2026-10-01T00:00:00", "status": "NotStarted", "isOverdue": False},
			{"id": 2, "title": "Klar uppgift", "dueDate": "2026-09-30", "status": "Done"},
			{"id": 3, "title": "Sen", "dueDate": "2026-09-20", "status": "NotStarted", "isOverdue": True},
			{"id": 4, "title": "Långt fram", "dueDate": "2026-12-01", "status": "NotStarted"},
			{"id": 5, "title": "Inget datum", "status": "NotStarted"},
		],
		"totalDue": 3,
		"totalOverdue": 1,
	}
	tasks = school_data.normalize_tasks(payload)
	assert tasks["total_due"] == 3 and tasks["items"][0]["title"] == "Läsläxa"
	due = school_data.tasks_due(tasks["items"], date(2026, 9, 29))
	assert [task["id"] for task in due] == ["3", "1"]


def test_normalize_tasks_unknown_shape_is_none():
	assert school_data.normalize_tasks(None) is None
	assert school_data.normalize_tasks([]) is None
	assert school_data.normalize_tasks({})["items"] == []


def test_calendar_drops_tasks_and_sorts_upcoming():
	entries = [
		{"id": 1, "title": "Utflykt", "startDate": "2026-10-02", "startDateFull": "2026-10-02T00:00:00", "isAllDayEvent": True, "url": None},
		{"id": 2, "title": "Uppgift", "startDate": "2026-10-01", "url": "/task/show/5"},
		{"id": 3, "title": "Prov", "startDate": "2026-10-01", "startTime": "09:00", "subjects": [{"title": "Ma"}]},
		{"id": 4, "title": "Förra veckan", "startDate": "2026-09-20"},
		{"id": 5, "title": "Lägerskola", "startDate": "2026-09-28", "endDate": "2026-09-30"},
	]
	events = school_data.normalize_calendar(entries)
	assert [event["id"] for event in events] == ["1", "3", "4", "5"]
	upcoming = school_data.upcoming_events(events, date(2026, 9, 29))
	assert [event["title"] for event in upcoming] == ["Lägerskola", "Prov", "Utflykt"]
	assert upcoming[1]["subjects"] == "Ma"


def test_parse_mateo_unit():
	assert school_data.parse_mateo_unit("123") == "123"
	assert school_data.parse_mateo_unit("https://meny.mateo.se/kommun/123") == "123"
	assert school_data.parse_mateo_unit("https://meny.mateo.se/kommun/123/ ") == "123"
	assert school_data.parse_mateo_unit("") is None
	assert school_data.parse_mateo_unit("kommun") is None


def test_mateo_menu_and_lunch_to_show():
	payload = [
		{"date": "2026-09-29T00:00:00.000Z", "meals": [{"name": "Torsk", "type": "Lunch 1"}, {"name": "Vegobollar", "type": "Lunch 2"}]},
		{"date": "2026-09-30T00:00:00.000Z", "meals": [{"name": "Pannkakor", "type": None}]},
		{"date": "2026-10-01T00:00:00.000Z", "meals": []},
	]
	menu = school_data.parse_mateo_days(payload)
	assert menu["2026-09-29"][0] == {"label": "Lunch 1", "dish": "Torsk"}
	assert menu["2026-09-30"][0]["label"] == "Lunch"

	assert school_data.lunch_to_show(menu, datetime(2026, 9, 29, 10))[0] == "2026-09-29"
	assert school_data.lunch_to_show(menu, datetime(2026, 9, 29, 15))[0] == "2026-09-30"
	# Empty days are skipped
	assert school_data.lunch_to_show(menu, datetime(2026, 9, 30, 15)) == (None, [])
	assert school_data.parse_mateo_days({"error": "x"}) == {}


def test_kit_events_match_pe_and_swimming_on_the_day():
	events = school_data.normalize_calendar([
		{"title": "Idrott", "startDate": "2026-10-01", "isAllDayEvent": True},
		{"title": "Läsläxa", "startDate": "2026-10-01", "isAllDayEvent": True},
		{"title": "Bad", "startDate": "2026-10-07"},
		{"title": "Badminton", "startDate": "2026-10-07"},
		{"title": "Lägerskola med simning", "startDate": "2026-10-06", "endDate": "2026-10-08"},
	])
	assert [e["title"] for e in school_data.kit_events(events, date(2026, 10, 1))] == ["Idrott"]
	assert [e["title"] for e in school_data.kit_events(events, date(2026, 10, 7))] == ["Bad", "Lägerskola med simning"]
	assert school_data.kit_events(events, date(2026, 10, 2)) == []
