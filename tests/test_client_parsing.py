#!/usr/bin/env python3
"""Unit tests for InfoMentorClient date/timetable parsing (no network, no HA)."""

import asyncio
import sys
from datetime import datetime, time
from pathlib import Path

import aiohttp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "infomentor"))

from infomentor.client import InfoMentorClient  # noqa: E402
from infomentor.exceptions import InfoMentorAPIError  # noqa: E402
from infomentor.models import InfoMentorNotification  # noqa: E402


@pytest.fixture
def client() -> InfoMentorClient:
	return InfoMentorClient(session=None)


@pytest.mark.parametrize(
	"raw, expected",
	[
		("2025-06-02", datetime(2025, 6, 2)),
		("2025-06-02T08:15:00", datetime(2025, 6, 2, 8, 15)),
		("2025-06-02T08:15:00Z", datetime(2025, 6, 2, 8, 15)),
		("2025-06-02T08:15:00.000", datetime(2025, 6, 2, 8, 15)),
		("2025-06-02T08:15:00+02:00", datetime(2025, 6, 2, 8, 15)),
		("02.06.2025", datetime(2025, 6, 2)),
	],
)
def test_parse_date_formats(client, raw, expected):
	assert client._parse_date_or_none(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "not a date", 12345])
def test_unparsable_dates_return_none(client, raw):
	assert client._parse_date_or_none(raw) is None


@pytest.mark.parametrize(
	"raw, expected",
	[
		("08:15", time(8, 15)),
		("08:15:30", time(8, 15, 30)),
		("2025-06-02T08:15:00", time(8, 15)),
		("2025-06-02T13:45:00.000", time(13, 45)),
		(None, None),
		(830, None),
	],
)
def test_parse_time(client, raw, expected):
	assert client._parse_time(raw) == expected


def test_timetable_entries_with_datetime_start_get_times(client):
	data = [
		{"id": 1, "title": "Matte", "start": "2025-06-02T08:15:00", "end": "2025-06-02T09:00:00"},
	]
	entries = client._parse_timetable_from_api(data, "123", datetime(2025, 6, 2), datetime(2025, 6, 8))
	assert len(entries) == 1
	assert entries[0].date.date() == datetime(2025, 6, 2).date()
	assert entries[0].start_time == time(8, 15)
	assert entries[0].end_time == time(9, 0)


def test_timetable_entry_with_bad_date_is_skipped_not_put_on_today(client):
	data = [{"id": 1, "title": "Matte", "startDate": "garbage"}]
	assert client._parse_timetable_from_api(data, "123", datetime(2025, 6, 2), datetime(2025, 6, 8)) == []


def test_time_registration_with_bad_date_is_skipped(client):
	data = {
		"days": [
			{"date": "garbage", "startDateTime": "2025-06-02T08:00:00", "endDateTime": "2025-06-02T16:00:00"},
			{"date": "2025-06-03", "startDateTime": "2025-06-03T08:00:00", "endDateTime": "2025-06-03T16:00:00"},
		]
	}
	regs = client._parse_time_registration_from_api(data, "123", datetime(2025, 6, 2), datetime(2025, 6, 8))
	assert [r.date.date() for r in regs] == [datetime(2025, 6, 3).date()]
	assert regs[0].start_time == time(8, 0)


class _FakeAuth:
	def __init__(self):
		self.authenticated = True
		self.pupil_ids = ["1", "2"]

	async def switch_pupil(self, pupil_id):
		return False


def test_news_raises_when_pupil_switch_fails(client):
	"""A failed switch must not return the previously selected pupil's news."""
	client.auth = _FakeAuth()
	client.authenticated = True
	# Private loop: asyncio.run() would unset the current loop other plugins rely on
	loop = asyncio.new_event_loop()
	try:
		with pytest.raises(InfoMentorAPIError):
			loop.run_until_complete(client.get_news("2"))
	finally:
		loop.close()


@pytest.mark.parametrize(
	"raw, expected",
	[
		("#/learnlog", "https://hub.infomentor.se/#/learnlog"),
		("/#/communication/news/2143358", "https://hub.infomentor.se/#/communication/news/2143358"),
		(
			"/#/calendarv2/whole_week?selectedYear=2026&selectedWeek=39&eventId=221744838",
			"https://hub.infomentor.se/#/calendarv2/whole_week?selectedYear=2026&selectedWeek=39&eventId=221744838",
		),
		("https://example.org/x", "https://example.org/x"),
	],
)
def test_notification_url_keeps_hub_route(raw, expected):
	"""Hub pages are "#/" client-side routes (URL shapes seen live)."""
	assert InfoMentorNotification.from_dict({"id": 5, "url": raw}).full_url == expected


def test_notification_ids_from_live_shape():
	notif = InfoMentorNotification.from_dict({
		"id": 70364636, "state": "New", "appType": "CalendarV2", "type": "CalendarV2UpcomingEvent",
		"title": "Kommande kalenderhändelse", "subTitle": "", "dateSent": "2026-09-24T07:14:56",
		"url": "/#/calendarv2/whole_week?selectedYear=2026&selectedWeek=39&eventId=221744838",
		"pupilIM2Id": 2981886, "pupilSourceId": "92_V|1806227557|NEMANDI_SKOLI",
	})
	assert notif.is_new
	assert notif.pupil_id == "1806227557"  # not the unrelated pupilIM2Id
	assert (notif.url_param("selectedWeek"), notif.url_param("eventId")) == ("39", "221744838")
	news = InfoMentorNotification.from_dict({"id": 1, "url": "/#/communication/news/2143358"})
	assert news.url_path_id == "2143358" and news.pupil_id is None


def test_hub_timetable_fields_from_notes(client):
	"""Shape of hub /timetable/timetable/gettimetablelist entries (seen live)."""
	data = [{
		"start": "2026-09-25T08:00:00", "end": "2026-09-25T09:25:00", "title": "Matematik",
		"startTime": "08:00", "endTime": "09:25", "allDay": False,
		"notes": {"roomInfo": "B12", "timetableNotes": "", "tutors": "Anna A"},
	}]
	(entry,) = client._parse_timetable_from_api(data, "1", datetime(2026, 9, 24), datetime(2026, 10, 4))
	assert (entry.teacher, entry.room, entry.is_all_day) == ("Anna A", "B12", False)
	assert (entry.start_time, entry.end_time) == (time(8, 0), time(9, 25))


def test_closed_and_leave_days_do_not_count_as_attendance(client):
	"""InfoMentor keeps planned times on closed/leave days (seen live on a studiedag)."""
	from infomentor.models import ScheduleDay

	data = {"days": [
		{"date": "2026-09-24T00:00:00", "startDateTime": "2026-09-24T07:45:00", "endDateTime": "2026-09-24T16:00:00",
		 "isLocked": True, "isSchoolClosed": True},
		{"date": "2026-09-29T00:00:00", "startDateTime": "2026-09-29T12:45:00", "endDateTime": "2026-09-29T16:10:00",
		 "onLeave": True},
		{"date": "2026-09-30T00:00:00", "startDateTime": "2026-09-30T12:45:00", "endDateTime": "2026-09-30T16:10:00"},
	]}
	regs = client._parse_time_registration_from_api(data, "1", datetime(2026, 9, 21), datetime(2026, 10, 4))
	by_day = {r.date.day: ScheduleDay(date=r.date, pupil_id="1", timetable_entries=[], time_registrations=[r]) for r in regs}
	assert not by_day[24].has_preschool_or_fritids and not by_day[24].has_school
	assert not by_day[29].has_preschool_or_fritids and by_day[29].earliest_start is None
	assert by_day[30].has_preschool_or_fritids and by_day[30].earliest_start == time(12, 45)


def test_cookie_backup_keeps_domains_for_duplicate_names():
	"""ASP.NET_SessionId exists on several InfoMentor hosts with different values (seen live)."""
	from yarl import URL
	from infomentor.auth import InfoMentorAuth

	async def run():
		jar = aiohttp.CookieJar()
		jar.update_cookies({"ASP.NET_SessionId": "hub-value"}, response_url=URL("https://hub.infomentor.se/"))
		jar.update_cookies({"ASP.NET_SessionId": "legacy-value"}, response_url=URL("https://infomentor.se/"))
		jar.update_cookies({"other": "x"}, response_url=URL("https://example.com/"))
		async with aiohttp.ClientSession(cookie_jar=jar) as session:
			auth = InfoMentorAuth(session)
			auth._backup_auth_cookies()
			backup = auth._auth_cookies_backup
		async with aiohttp.ClientSession() as fresh:
			auth2 = InfoMentorAuth(fresh)
			auth2._auth_cookies_backup = backup
			assert auth2._restore_auth_cookies()
			restored = {(c["domain"], c.key, c.value) for c in fresh.cookie_jar}
		return backup, restored

	loop = asyncio.new_event_loop()
	try:
		backup, restored = loop.run_until_complete(run())
	finally:
		loop.close()
	assert len(backup) == 2  # example.com excluded
	assert restored == {
		("hub.infomentor.se", "ASP.NET_SessionId", "hub-value"),
		("infomentor.se", "ASP.NET_SessionId", "legacy-value"),
	}


def test_legacy_flat_cookie_backup_is_not_restored():
	from infomentor.auth import InfoMentorAuth

	auth = InfoMentorAuth(session=None)
	auth._auth_cookies_backup = {"ASP.NET_SessionId": "x"}
	assert auth._restore_auth_cookies() is False
