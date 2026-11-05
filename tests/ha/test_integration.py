"""Home Assistant-level tests for the InfoMentor integration, using a fake client.

Run with pytest-homeassistant-custom-component installed:
	pytest tests/ha
"""

import asyncio
import time as _time
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.infomentor.const import (
	CONF_MATEO_UNIT,
	CONF_NOTIFY_SERVICES,
	MATEO_API,
	CONF_PERSISTENT_NOTIFICATION,
	CONF_NOTIFICATION_TAP,
	DOMAIN,
	EVENT_NEW_NOTIFICATION,
	NOTIFICATION_TAP_APP,
	NOTIFICATION_TAP_NEW_APP,
)
from custom_components.infomentor.infomentor.check_in_out import CheckInOut, SCHOOL_TIME_ZONE
from custom_components.infomentor.infomentor.exceptions import InfoMentorAppUnavailableError
from custom_components.infomentor.infomentor.models import (
	InfoMentorNotification,
	PupilInfo,
	ScheduleDay,
	TimeRegistrationEntry,
	TimetableEntry,
)

USERNAME = "parent@example.com"
PUPIL_ID = "1"


class FakeAuth:
	def __init__(self) -> None:
		self.authenticated = False
		self.pupil_ids: list[str] = []
		self._last_auth_time = None

	def is_auth_likely_expired(self) -> bool:
		return not self.authenticated

	async def diagnose_auth_state(self) -> dict:
		return {}


class FakeClient:
	"""Stand-in for InfoMentorClient; class attributes hold per-test state."""

	login_calls = 0
	schedule_calls = 0
	notifications: list[InfoMentorNotification] = []
	notifications_broken = False
	check_in_out_calls = 0
	check_in_out_broken = False
	check_in_out_payload = {"checkedIn": "08:15", "checkedOut": ""}
	# {date: [lesson titles]}; empty = time registrations only
	lessons: dict = {}
	tasks: dict | None = None
	timeline_calls = 0
	timeline_unavailable = False

	def __init__(self, session=None, storage=None) -> None:
		self.auth = FakeAuth()
		self.authenticated = False

	async def __aenter__(self):
		return self

	async def __aexit__(self, *args):
		return None

	async def try_restore_session(self) -> bool:
		return False

	async def login(self, username, password) -> bool:
		FakeClient.login_calls += 1
		self.auth.authenticated = self.authenticated = True
		self.auth.pupil_ids = [PUPIL_ID]
		self.auth._last_auth_time = _time.time()
		return True

	async def get_pupil_ids(self):
		return list(self.auth.pupil_ids)

	async def get_pupil_info(self, pupil_id):
		return PupilInfo(id=pupil_id, name="Alice")

	async def get_news(self, pupil_id):
		return []

	async def get_timeline(self, pupil_id):
		FakeClient.timeline_calls += 1
		if FakeClient.timeline_unavailable:
			# What InfoMentor answers when the school has the timeline turned off
			raise InfoMentorAppUnavailableError("InfoMentor does not give this account access to the timeline")
		return []

	async def get_schedule(self, pupil_id, start_date, end_date):
		FakeClient.schedule_calls += 1
		days = []
		day = start_date
		while day <= end_date:
			regs = []
			if day.weekday() < 5:
				regs.append(TimeRegistrationEntry(id=str(day.date()), date=day, start_time=time(8), end_time=time(16)))
			entries = [
				TimetableEntry(id=f"{day.date()}{i}", title=title, date=day, subject=title, start_time=time(9 + i), end_time=time(10 + i))
				for i, title in enumerate(FakeClient.lessons.get(day.date(), []))
			]
			days.append(ScheduleDay(date=day, pupil_id=pupil_id, timetable_entries=entries, time_registrations=regs))
			day += timedelta(days=1)
		return days

	async def get_check_in_out(self, pupil_id, day):
		FakeClient.check_in_out_calls += 1
		if FakeClient.check_in_out_broken:
			raise RuntimeError("check-in/out endpoint down")
		return CheckInOut.from_response({"date": day.isoformat(), **FakeClient.check_in_out_payload}, day)

	async def get_notifications(self):
		if FakeClient.notifications_broken:
			raise RuntimeError("notification endpoint down")
		return list(FakeClient.notifications)

	async def warmup_hub_session(self) -> bool:
		return True

	async def switch_pupil(self, pupil_id) -> bool:
		return True

	async def get_calendar_entries(self, pupil_id, start_date, end_date):
		# Shape of /calendarv2/calendarv2/getentries (seen live)
		return [{
			"id": 555, "title": "Studiedag", "text": "<p>Skolan är stängd.</p>", "isAllDayEvent": True,
			"startDate": "2026-09-24", "formattedStartDate": "tor 24 sep", "formattedEndDate": "tor 24 sep",
			"startTime": None,
		}]

	async def get_tasks(self, pupil_id):
		if FakeClient.tasks is None:
			# What preschool pupils get
			raise RuntimeError("/task/task/GetTasks: HTTP 500")
		return FakeClient.tasks

	async def get_learnlogs(self, pupil_id):
		return [{"id": 1, "title": "Höstlov V.44", "subjectsCoursesDisplayString": "Fritidshem", "text": "<p>x</p>"}]


def _notification(notif_id: int, state: str = "New") -> InfoMentorNotification:
	# Shape of a NotificationApp item (seen live)
	return InfoMentorNotification.from_dict({
		"id": notif_id, "title": "Kommande kalenderhändelse", "subTitle": "", "state": state,
		"appType": "CalendarV2", "type": "CalendarV2UpcomingEvent", "dateSent": "2026-09-23T10:00:00",
		"url": "/#/calendarv2/whole_week?selectedYear=2026&selectedWeek=39&eventId=555",
		"pupilIM2Id": 3000001, "pupilSourceId": f"92_V|{PUPIL_ID}|SCHOOL",
	})


@pytest.fixture(autouse=True)
def fake_client(freezer):
	# Mid-week, well away from the "first 5 minutes of the hour" maintenance window
	freezer.move_to(dt_util.as_utc(datetime(2026, 9, 23, 10, 30, tzinfo=dt_util.get_default_time_zone())))
	FakeClient.login_calls = 0
	FakeClient.schedule_calls = 0
	FakeClient.notifications = []
	FakeClient.notifications_broken = False
	FakeClient.check_in_out_calls = 0
	FakeClient.check_in_out_broken = False
	FakeClient.check_in_out_payload = {"checkedIn": "08:15", "checkedOut": ""}
	FakeClient.lessons = {}
	FakeClient.tasks = None
	FakeClient.timeline_calls = 0
	FakeClient.timeline_unavailable = False
	with patch("custom_components.infomentor.coordinator.InfoMentorClient", FakeClient):
		yield FakeClient


async def _setup(hass: HomeAssistant, entry: MockConfigEntry | None = None) -> MockConfigEntry:
	if entry is None:
		entry = MockConfigEntry(domain=DOMAIN, data={"username": USERNAME, "password": "pw"}, unique_id=USERNAME)
		entry.add_to_hass(hass)
	assert await hass.config_entries.async_setup(entry.entry_id)
	await hass.async_block_till_done()
	assert entry.state is ConfigEntryState.LOADED
	return entry


async def test_later_refreshes_fetch_fresh_data(hass: HomeAssistant) -> None:
	"""Previously every refresh within 72h of the last fetch returned cached data."""
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	assert FakeClient.schedule_calls == 1
	assert FakeClient.login_calls == 1  # no second login straight after setup
	# Complete data on the very first fetch -> normal 12h interval, not the hourly retry
	assert coordinator.update_interval == timedelta(hours=12)

	await coordinator.force_refresh(clear_cache=False)
	assert FakeClient.schedule_calls == 2

	await hass.config_entries.async_unload(entry.entry_id)


def _entity_state(hass, suffix):
	"""Find entity IDs with or without the account/device prefix used by HA."""
	return next((state for state in hass.states.async_all()
		if state.entity_id.endswith(suffix)
		or state.entity_id.endswith(f".{suffix.removeprefix('_')}")), None)


def _check_in_out_states(hass):
	registry = er.async_get(hass)
	ids = {e.entity_id for e in registry.entities.values() if e.platform == DOMAIN
		and e.unique_id.endswith((f"_check_in_{PUPIL_ID}", f"_check_out_{PUPIL_ID}"))}
	return [s for s in hass.states.async_all("sensor") if s.entity_id in ids]


async def test_check_in_out_sensors_and_five_minute_refresh(hass: HomeAssistant, freezer) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	states = _check_in_out_states(hass)
	assert len(states) == 2
	check_in = next(s for s in states if s.entity_id.endswith("_check_in"))
	check_out = next(s for s in states if s.entity_id.endswith("_check_out"))
	assert check_in.attributes["device_class"] == "timestamp"
	assert datetime.fromisoformat(check_in.state).astimezone(SCHOOL_TIME_ZONE).hour == 8
	assert check_out.state == "unknown"
	schedule_calls = FakeClient.schedule_calls
	check_in_out_calls = FakeClient.check_in_out_calls
	FakeClient.check_in_out_payload = {"checkedIn": "08:15", "checkedOut": "16:20"}
	freezer.tick(timedelta(minutes=5, seconds=1))
	async_fire_time_changed(hass)
	await hass.async_block_till_done()
	assert FakeClient.check_in_out_calls == check_in_out_calls + 1
	assert FakeClient.schedule_calls == schedule_calls
	assert datetime.fromisoformat(hass.states.get(check_out.entity_id).state).astimezone(SCHOOL_TIME_ZONE).hour == 16
	await hass.config_entries.async_unload(entry.entry_id)


async def test_check_in_out_failure_is_unavailable_then_recovers(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	FakeClient.check_in_out_broken = True
	await coordinator._async_notification_tick()
	assert all(s.state == "unavailable" for s in _check_in_out_states(hass))
	FakeClient.check_in_out_broken = False
	await coordinator._async_notification_tick()
	assert all(s.state != "unavailable" for s in _check_in_out_states(hass))
	await hass.config_entries.async_unload(entry.entry_id)


async def test_check_in_out_clears_yesterday_at_midnight(hass: HomeAssistant, freezer) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	freezer.tick(timedelta(days=1))
	coordinator._async_midnight_rollover(dt_util.now())
	assert all(s.state == "unknown" for s in _check_in_out_states(hass))
	await hass.config_entries.async_unload(entry.entry_id)


async def test_check_in_out_updates_during_notification_backoff(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	coordinator._notification_retry_at = dt_util.utcnow() + timedelta(hours=1)
	before = FakeClient.check_in_out_calls
	await coordinator._async_notification_tick()
	assert FakeClient.check_in_out_calls == before + 1
	await hass.config_entries.async_unload(entry.entry_id)


async def test_check_in_out_manual_refresh(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	before = FakeClient.check_in_out_calls
	await coordinator.async_refresh_pupil_data(PUPIL_ID)
	assert FakeClient.check_in_out_calls == before + 1
	await coordinator.force_refresh(clear_cache=False)
	assert FakeClient.check_in_out_calls == before + 2
	await hass.config_entries.async_unload(entry.entry_id)


async def test_check_in_out_isolates_child_failures_under_api_lock(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	coordinator.pupil_ids = [PUPIL_ID, "2"]

	async def get_times(pupil_id, day):
		assert coordinator._api_lock.locked()
		if pupil_id == PUPIL_ID:
			raise RuntimeError("endpoint failed for this child")
		return CheckInOut.from_response({"date": day.isoformat(), "checkedIn": "09:12", "checkedOut": ""}, day)

	coordinator.client.get_check_in_out = get_times
	await coordinator._async_notification_tick()
	assert coordinator.check_in_out_failed == {PUPIL_ID}
	assert coordinator.check_in_out["2"].checked_in.hour == 9
	await hass.config_entries.async_unload(entry.entry_id)


async def test_check_in_out_swedish_names(hass: HomeAssistant) -> None:
	hass.config.language = "sv"
	entry = await _setup(hass)
	states = _check_in_out_states(hass)
	assert {s.name for s in states} == {
		f"InfoMentor Account ({USERNAME}) Alice Incheckning",
		f"InfoMentor Account ({USERNAME}) Alice Utcheckning",
	}
	await hass.config_entries.async_unload(entry.entry_id)


async def test_slow_check_in_out_does_not_delay_platform_setup(hass: HomeAssistant) -> None:
	entered = asyncio.Event()
	release = asyncio.Event()
	original = FakeClient.get_check_in_out

	async def slow_read(client, pupil_id, day):
		entered.set()
		await release.wait()
		return await original(client, pupil_id, day)

	with patch.object(FakeClient, "get_check_in_out", slow_read):
		setup_task = asyncio.create_task(_setup(hass))
		try:
			await asyncio.wait_for(entered.wait(), 5)
			entry = await asyncio.wait_for(asyncio.shield(setup_task), 1)
			assert entry.state is ConfigEntryState.LOADED
			assert _entity_state(hass, "_alice_today_schedule").state != "unavailable"
			assert len(_check_in_out_states(hass)) == 2
			assert all(s.state == "unknown" for s in _check_in_out_states(hass))
		finally:
			release.set()
			entry = await setup_task
			coordinator = hass.data[DOMAIN][entry.entry_id]
			await coordinator._check_in_out_startup_task
			await hass.async_block_till_done()
			assert any(s.state not in ("unknown", "unavailable") for s in _check_in_out_states(hass))
			await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_cancels_pending_initial_check_in_out(hass: HomeAssistant) -> None:
	entered = asyncio.Event()
	cancelled = asyncio.Event()

	async def slow_read(client, pupil_id, day):
		entered.set()
		try:
			await asyncio.Event().wait()
		finally:
			cancelled.set()

	with patch.object(FakeClient, "get_check_in_out", slow_read):
		setup_task = asyncio.create_task(_setup(hass))
		await asyncio.wait_for(entered.wait(), 5)
		entry = await asyncio.wait_for(asyncio.shield(setup_task), 1)
		coordinator = hass.data[DOMAIN][entry.entry_id]
		task = coordinator._check_in_out_startup_task
		assert await hass.config_entries.async_unload(entry.entry_id)
		assert task.cancelled()
		assert cancelled.is_set()
		assert coordinator.client is None


async def test_check_in_out_english_names(hass: HomeAssistant) -> None:
	hass.config.language = "en"
	entry = await _setup(hass)
	assert {s.name for s in _check_in_out_states(hass)} == {
		f"InfoMentor Account ({USERNAME}) Alice Check-in",
		f"InfoMentor Account ({USERNAME}) Alice Check-out",
	}
	await hass.config_entries.async_unload(entry.entry_id)


async def test_startup_uses_cache_then_schedules_normal_refresh(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	assert await hass.config_entries.async_unload(entry.entry_id)
	FakeClient.schedule_calls = FakeClient.login_calls = 0

	await _setup(hass, entry)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	assert FakeClient.schedule_calls == 0
	assert coordinator.data and PUPIL_ID in coordinator.data
	assert coordinator.update_interval > timedelta(hours=11)

	await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_stops_polling(hass: HomeAssistant, freezer) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	assert await hass.config_entries.async_unload(entry.entry_id)
	calls = FakeClient.schedule_calls

	freezer.tick(timedelta(hours=13))
	async_fire_time_changed(hass)
	await hass.async_block_till_done()
	assert FakeClient.schedule_calls == calls
	assert coordinator._unsub_timers == []


async def test_notifications_pushed_once_and_not_after_restart(hass: HomeAssistant, freezer) -> None:
	pushed: list[ServiceCall] = []

	async def _notify(call: ServiceCall) -> None:
		pushed.append(call)

	hass.services.async_register("notify", "test_phone", _notify)
	events = []
	hass.bus.async_listen(EVENT_NEW_NOTIFICATION, events.append)

	FakeClient.notifications = [_notification(1)]
	entry = MockConfigEntry(
		domain=DOMAIN,
		data={"username": USERNAME, "password": "pw"},
		options={CONF_NOTIFY_SERVICES: ["test_phone"]},
		unique_id=USERNAME,
	)
	entry.add_to_hass(hass)
	await _setup(hass, entry)
	# First ever check only records existing notifications
	assert events == [] and pushed == []

	# The 5-minute poller picks up a new one without a data refresh
	FakeClient.notifications = [_notification(2), _notification(1)]
	freezer.tick(timedelta(minutes=5, seconds=1))
	async_fire_time_changed(hass)
	await hass.async_block_till_done()
	assert [e.data["id"] for e in events] == [2]
	assert len(pushed) == 1
	# Child's name, the event itself and a tap target that keeps the hub's "#/" route
	assert pushed[0].data["title"] == "Alice: Kommande kalenderhändelse"
	assert pushed[0].data["message"] == "Studiedag · tor 24 sep (heldag) — Skolan är stängd."
	assert pushed[0].data["data"]["clickAction"].startswith("https://hub.infomentor.se/#/calendarv2/")
	# A group makes the Android app add an empty summary that opens HA's default page
	assert "group" not in pushed[0].data["data"]
	assert events[0].data["pupil_name"] == "Alice" and events[0].data["detail"] == pushed[0].data["message"]
	assert hass.data[DOMAIN][entry.entry_id].schedule_is_complete()

	# After a restart the same notifications must not be pushed again
	assert await hass.config_entries.async_unload(entry.entry_id)
	await _setup(hass, entry)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	async with coordinator._api_lock:
		await coordinator._background_auth_check_locked()
	await coordinator._async_notification_tick()
	assert [e.data["id"] for e in events] == [2]
	assert len(pushed) == 1

	await hass.config_entries.async_unload(entry.entry_id)


async def test_android_phones_are_asked_once_what_a_tap_opens(hass: HomeAssistant) -> None:
	pushed: list[ServiceCall] = []

	async def _notify(call: ServiceCall) -> None:
		pushed.append(call)

	for name, os_name in (("Pixel", "Android"), ("iPhone", "iOS")):
		MockConfigEntry(domain="mobile_app", data={"device_name": name, "os_name": os_name}).add_to_hass(hass)
		hass.services.async_register("notify", f"mobile_app_{name.lower()}", _notify)
	entry = MockConfigEntry(
		domain=DOMAIN,
		data={"username": USERNAME, "password": "pw"},
		options={CONF_NOTIFY_SERVICES: ["mobile_app_pixel", "mobile_app_iphone"], CONF_NOTIFICATION_TAP: "browser"},
		unique_id=USERNAME,
	)
	entry.add_to_hass(hass)
	await _setup(hass, entry)
	coordinator = hass.data[DOMAIN][entry.entry_id]

	await coordinator._async_notification_tick()
	await coordinator._async_notification_tick()
	# Asked once, and only on the Android phone; tapping the question shows the new app
	assert [call.service for call in pushed] == ["mobile_app_pixel"]
	question = pushed[0].data["data"]
	assert question["clickAction"] == "https://play.google.com/store/apps/details?id=net.infomentor.imhome"
	assert [a["action"] for a in question["actions"]] == [
		f"INFOMENTOR_TAP:{entry.entry_id}:browser",
		f"INFOMENTOR_TAP:{entry.entry_id}:new_app",
		f"INFOMENTOR_TAP:{entry.entry_id}:app",
	]

	# Another account's answer is ignored
	hass.bus.async_fire("mobile_app_notification_action", {"action": "INFOMENTOR_TAP:other:app"})
	hass.bus.async_fire("mobile_app_notification_action", {"action": f"INFOMENTOR_TAP:{entry.entry_id}:new_app"})
	await hass.async_block_till_done()
	assert entry.options[CONF_NOTIFICATION_TAP] == "new_app"
	assert entry.options[CONF_NOTIFY_SERVICES] == ["mobile_app_pixel", "mobile_app_iphone"]
	# The confirmation replaces the question and opens the chosen app
	confirm = pushed[-1].data
	assert len(pushed) == 2 and confirm["data"]["tag"] == question["tag"]
	assert confirm["data"]["clickAction"] == "app://net.infomentor.imhome"
	assert "Configure" in confirm["message"]

	# Not asked again after a restart, even if set back to the browser
	hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_NOTIFICATION_TAP: "browser"})
	await hass.config_entries.async_reload(entry.entry_id)
	await hass.async_block_till_done()
	await hass.data[DOMAIN][entry.entry_id]._async_notification_tick()
	assert len(pushed) == 2

	await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
	("tap", "package"),
	[(NOTIFICATION_TAP_APP, "net.infomentor.android"), (NOTIFICATION_TAP_NEW_APP, "net.infomentor.imhome")],
)
async def test_tap_can_open_infomentor_app(hass: HomeAssistant, tap: str, package: str) -> None:
	pushed: list[ServiceCall] = []

	async def _notify(call: ServiceCall) -> None:
		pushed.append(call)

	hass.services.async_register("notify", "phone", _notify)
	entry = MockConfigEntry(
		domain=DOMAIN,
		data={"username": USERNAME, "password": "pw"},
		options={CONF_NOTIFY_SERVICES: ["phone"], CONF_NOTIFICATION_TAP: tap},
		unique_id=USERNAME,
	)
	entry.add_to_hass(hass)
	await _setup(hass, entry)
	FakeClient.notifications = [_notification(4)]
	coordinator = hass.data[DOMAIN][entry.entry_id]
	await coordinator._async_notification_tick()
	await hass.services.async_call("button", "press", {"entity_id": "button.infomentor_send_test_notification"}, blocking=True)

	data = pushed[-1].data["data"]
	assert data["clickAction"] == f"app://{package}"
	# The item itself stays reachable, and iOS keeps the web link
	assert data["actions"] == [{"action": "URI", "title": "Open in browser", "uri": data["url"]}]
	assert data["url"].startswith("https://hub.infomentor.se/#/calendarv2/")

	await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_timeline_is_not_retried_every_refresh(hass: HomeAssistant, freezer) -> None:
	FakeClient.timeline_unavailable = True
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	assert FakeClient.timeline_calls == 1
	assert coordinator.data[PUPIL_ID]["timeline"] == []
	# The rest of the refresh still counts as complete
	assert coordinator.schedule_is_complete()

	await coordinator.force_refresh(clear_cache=False)
	assert FakeClient.timeline_calls == 1

	# Checked again a day later, in case the school turns it back on
	freezer.tick(timedelta(hours=24, minutes=1))
	FakeClient.timeline_unavailable = False
	await coordinator.force_refresh(clear_cache=False)
	assert FakeClient.timeline_calls == 2
	await coordinator.force_refresh(clear_cache=False)
	assert FakeClient.timeline_calls == 3

	await hass.config_entries.async_unload(entry.entry_id)


async def test_today_rolls_over_at_midnight(hass: HomeAssistant, freezer) -> None:
	entry = await _setup(hass)
	coordinator = hass.data[DOMAIN][entry.entry_id]
	today = dt_util.now().date()
	assert coordinator.get_cached_today_schedule(PUPIL_ID).date.date() == today

	freezer.move_to(dt_util.as_utc(datetime.combine(today + timedelta(days=1), time(0, 0, 6), dt_util.get_default_time_zone())))
	async_fire_time_changed(hass)
	await hass.async_block_till_done()
	assert coordinator.get_cached_today_schedule(PUPIL_ID).date.date() == today + timedelta(days=1)
	assert coordinator.get_cached_tomorrow_schedule(PUPIL_ID).date.date() == today + timedelta(days=2)

	await hass.config_entries.async_unload(entry.entry_id)


async def test_service_accepts_device_target(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	device = next(iter(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)))
	await hass.services.async_call(
		DOMAIN, "force_refresh", {"device_id": [device.id], "clear_cache": False}, blocking=True
	)
	assert FakeClient.schedule_calls == 2

	await hass.config_entries.async_unload(entry.entry_id)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
	with patch("custom_components.infomentor.config_flow._test_credentials", AsyncMock()), patch(
		"custom_components.infomentor.async_setup_entry", AsyncMock(return_value=True)
	):
		result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
		assert result["type"] is FlowResultType.FORM
		result = await hass.config_entries.flow.async_configure(
			result["flow_id"], {"username": USERNAME, "password": "pw"}
		)
	assert result["type"] is FlowResultType.CREATE_ENTRY
	assert result["data"] == {"username": USERNAME, "password": "pw"}


async def test_options_flow_sets_notify_services_without_password(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	test_credentials = AsyncMock()
	with patch("custom_components.infomentor.config_flow._test_credentials", test_credentials):
		result = await hass.config_entries.options.async_init(entry.entry_id)
		assert result["type"] is FlowResultType.FORM
		result = await hass.config_entries.options.async_configure(
			result["flow_id"],
			{"username": USERNAME, CONF_NOTIFY_SERVICES: ["mobile_app_phone"], CONF_PERSISTENT_NOTIFICATION: True},
		)
	assert result["type"] is FlowResultType.CREATE_ENTRY
	assert entry.options == {
		CONF_NOTIFY_SERVICES: ["mobile_app_phone"],
		CONF_PERSISTENT_NOTIFICATION: True,
		CONF_NOTIFICATION_TAP: "browser",
		CONF_MATEO_UNIT: "",
	}
	assert entry.data["password"] == "pw"
	test_credentials.assert_not_awaited()

	await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_updates_password(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	with patch("custom_components.infomentor.config_flow._test_credentials", AsyncMock()):
		result = await entry.start_reauth_flow(hass)
		assert result["step_id"] == "reauth_confirm"
		result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new"})
		await hass.async_block_till_done()
	assert result["type"] is FlowResultType.ABORT
	assert result["reason"] == "reauth_successful"
	assert entry.data == {"username": USERNAME, "password": "new"}
	assert len(hass.config_entries.async_entries(DOMAIN)) == 1

	await hass.config_entries.async_unload(entry.entry_id)


async def test_failing_notification_endpoint_backs_off_logins(hass: HomeAssistant, freezer) -> None:
	entry = await _setup(hass)
	FakeClient.notifications_broken = True
	logins_after_setup = FakeClient.login_calls

	# Six 5-minute ticks: without backoff every tick after a failure would re-login
	for _ in range(6):
		freezer.tick(timedelta(minutes=5, seconds=1))
		async_fire_time_changed(hass)
		await hass.async_block_till_done()
	assert FakeClient.login_calls - logins_after_setup <= 1

	# Recovers once the endpoint works again
	FakeClient.notifications_broken = False
	FakeClient.notifications = [_notification(7)]
	freezer.tick(timedelta(hours=2, minutes=1))
	async_fire_time_changed(hass)
	await hass.async_block_till_done()
	assert [n.id for n in hass.data[DOMAIN][entry.entry_id].notifications] == [7]

	await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_lists_notify_services(hass: HomeAssistant) -> None:
	hass.services.async_register("notify", "mobile_app_pixel", lambda call: None)
	entry = await _setup(hass)
	result = await hass.config_entries.options.async_init(entry.entry_id)
	selector = result["data_schema"].schema[CONF_NOTIFY_SERVICES]
	options = [o if isinstance(o, str) else o["value"] for o in selector.config["options"]]
	assert "mobile_app_pixel" in options
	hass.config_entries.options.async_abort(result["flow_id"])
	await hass.config_entries.async_unload(entry.entry_id)


async def test_legacy_comma_separated_option_still_works(hass: HomeAssistant, freezer) -> None:
	pushed: list[ServiceCall] = []

	async def _notify(call: ServiceCall) -> None:
		pushed.append(call)

	hass.services.async_register("notify", "a", _notify)
	hass.services.async_register("notify", "b", _notify)
	entry = MockConfigEntry(
		domain=DOMAIN, data={"username": USERNAME, "password": "pw"},
		options={CONF_NOTIFY_SERVICES: "a, notify.b"}, unique_id=USERNAME,
	)
	entry.add_to_hass(hass)
	await _setup(hass, entry)
	FakeClient.notifications = [_notification(9)]
	freezer.tick(timedelta(minutes=5, seconds=1))
	async_fire_time_changed(hass)
	await hass.async_block_till_done()
	assert len(pushed) == 2
	await hass.config_entries.async_unload(entry.entry_id)


async def test_test_notification_button(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	button_id = _entity_state(hass, "_infomentor_send_test_notification").entity_id
	# No targets configured: the press fails with a helpful error
	with pytest.raises(HomeAssistantError, match="Configure"):
		await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)

	pushed: list[ServiceCall] = []

	async def _notify(call: ServiceCall) -> None:
		pushed.append(call)

	hass.services.async_register("notify", "phone", _notify)
	hass.config_entries.async_update_entry(
		entry, options={CONF_NOTIFY_SERVICES: ["phone"], CONF_PERSISTENT_NOTIFICATION: True}
	)
	FakeClient.notifications = [_notification(3)]
	coordinator = hass.data[DOMAIN][entry.entry_id]
	await coordinator._async_notification_tick()
	await hass.services.async_call("button", "press", {"entity_id": button_id}, blocking=True)
	assert pushed[-1].data["title"] == "(Test) Alice: Kommande kalenderhändelse"
	from homeassistant.components import persistent_notification

	assert "infomentor_test" in persistent_notification._async_get_or_create_notifications(hass)
	await hass.config_entries.async_unload(entry.entry_id)


async def test_assignments_next_event_and_pe(hass: HomeAssistant) -> None:
	# Wednesday 23 Sep; Thursday is the next school day and has PE
	FakeClient.lessons = {datetime(2026, 9, 24).date(): ["Ma", "Idh"], datetime(2026, 9, 25).date(): ["Sv"]}
	FakeClient.tasks = {
		"items": [
			{"id": 1, "title": "Läsläxa", "subject": "Sv", "dueDate": "2026-09-25T00:00:00", "status": "NotStarted"},
			{"id": 2, "title": "Gammal", "dueDate": "2026-09-01T00:00:00", "status": "Done"},
		],
		"totalDue": 1, "totalOverdue": 0,
	}
	entry = await _setup(hass)

	assignments = _entity_state(hass, "_alice_assignments_due")
	assert assignments.state == "1"
	assert assignments.attributes["assignments"][0]["title"] == "Läsläxa"

	event = _entity_state(hass, "_alice_next_event")
	assert event.state == "Studiedag"
	assert event.attributes["date"] == "2026-09-24"
	assert event.attributes["description"] == "Skolan är stängd."

	pe = _entity_state(hass, "_alice_pe_next_school_day")
	assert pe.state == "on"
	assert pe.attributes["date"] == "2026-09-24" and pe.attributes["times"] == ["10:00"]

	# Both survive a restart that serves cached data without fetching
	assert await hass.config_entries.async_unload(entry.entry_id)
	FakeClient.schedule_calls = 0
	await _setup(hass, entry)
	assert FakeClient.schedule_calls == 0
	assert _entity_state(hass, "_alice_assignments_due").state == "1"
	assert _entity_state(hass, "_alice_next_event").state == "Studiedag"
	assert _entity_state(hass, "_alice_pe_next_school_day").state == "on"
	await hass.config_entries.async_unload(entry.entry_id)


async def test_assignments_unknown_without_task_app(hass: HomeAssistant) -> None:
	entry = await _setup(hass)
	state = _entity_state(hass, "_alice_assignments_due")
	assert state.state == "unknown" and state.attributes["available"] is False
	# Only time registrations, no lessons -> no PE
	assert _entity_state(hass, "_alice_pe_next_school_day").state == "off"
	await hass.config_entries.async_unload(entry.entry_id)


async def test_lunch_option_adds_sensor(hass: HomeAssistant, aioclient_mock) -> None:
	aioclient_mock.get(f"{MATEO_API}/123", json=[
		{"date": "2026-09-23T00:00:00.000Z", "meals": [{"name": "Fiskgratäng", "type": "Lunch 1"}, {"name": "Broccolipaj", "type": "Lunch 2"}]},
		{"date": "2026-09-24T00:00:00.000Z", "meals": [{"name": "Pannkakor", "type": "Lunch 1"}]},
	])
	entry = await _setup(hass)
	assert _entity_state(hass, "_infomentor_school_lunch") is None

	result = await hass.config_entries.options.async_init(entry.entry_id)
	result = await hass.config_entries.options.async_configure(
		result["flow_id"], {"username": USERNAME, CONF_MATEO_UNIT: "nothing here"}
	)
	assert result["errors"] == {CONF_MATEO_UNIT: "invalid_mateo_unit"}
	result = await hass.config_entries.options.async_configure(
		result["flow_id"], {"username": USERNAME, CONF_MATEO_UNIT: "https://meny.mateo.se/kommun/123"}
	)
	assert result["type"] is FlowResultType.CREATE_ENTRY
	await hass.async_block_till_done()

	# The option change reloaded the entry, which added the sensor and fetched the menu
	lunch = _entity_state(hass, "_infomentor_school_lunch")
	assert lunch.state == "Fiskgratäng; Broccolipaj"
	assert lunch.attributes["date"] == "2026-09-23" and lunch.attributes["unit"] == "123"
	assert lunch.attributes["menu"]["2026-09-24"] == ["Pannkakor"]
	await hass.config_entries.async_unload(entry.entry_id)


async def test_today_and_tomorrow_schedule_describe_days_the_same_way(hass: HomeAssistant) -> None:
	"""im-tools#1: Today showed "preschool_fritids" while Tomorrow showed "Preschool (08:00-16:00)"."""
	entry = await _setup(hass)
	today = next(s for s in hass.states.async_all("sensor") if s.entity_id.endswith("_today_schedule"))
	tomorrow = next(s for s in hass.states.async_all("sensor") if s.entity_id.endswith("_tomorrow_schedule"))

	# Wednesday and Thursday, both 08:00-16:00 care, no lessons: a preschool child
	assert today.state == "preschool_fritids"  # documented status code, unchanged
	assert today.attributes["summary"] == "Preschool (08:00-16:00)"
	assert tomorrow.state == "Preschool (08:00-16:00)"
	assert tomorrow.attributes["status"] == "preschool_fritids"

	await hass.config_entries.async_unload(entry.entry_id)
