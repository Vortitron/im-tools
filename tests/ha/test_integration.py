"""Home Assistant-level tests for the InfoMentor integration, using a fake client.

Run with pytest-homeassistant-custom-component installed:
	pytest tests/ha
"""

import time as _time
from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.infomentor.const import (
	CONF_NOTIFY_SERVICES,
	CONF_PERSISTENT_NOTIFICATION,
	DOMAIN,
	EVENT_NEW_NOTIFICATION,
)
from custom_components.infomentor.infomentor.models import (
	InfoMentorNotification,
	PupilInfo,
	ScheduleDay,
	TimeRegistrationEntry,
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
		return []

	async def get_schedule(self, pupil_id, start_date, end_date):
		FakeClient.schedule_calls += 1
		days = []
		day = start_date
		while day <= end_date:
			regs = []
			if day.weekday() < 5:
				regs.append(TimeRegistrationEntry(id=str(day.date()), date=day, start_time=time(8), end_time=time(16)))
			days.append(ScheduleDay(date=day, pupil_id=pupil_id, timetable_entries=[], time_registrations=regs))
			day += timedelta(days=1)
		return days

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

	async def get_learnlogs(self, pupil_id):
		return [{"id": 1, "title": "Höstlov V.44", "subjectsCoursesDisplayString": "Fritidshem", "text": "<p>x</p>"}]


def _notification(notif_id: int, state: str = "New") -> InfoMentorNotification:
	# Shape of a NotificationApp item (seen live)
	return InfoMentorNotification.from_dict({
		"id": notif_id, "title": "Kommande kalenderhändelse", "subTitle": "", "state": state,
		"appType": "CalendarV2", "type": "CalendarV2UpcomingEvent", "dateSent": "2026-09-23T10:00:00",
		"url": "/#/calendarv2/whole_week?selectedYear=2026&selectedWeek=39&eventId=555",
		"pupilIM2Id": 2981886, "pupilSourceId": f"92_V|{PUPIL_ID}|SCHOOL",
	})


@pytest.fixture(autouse=True)
def fake_client(freezer):
	# Mid-week, well away from the "first 5 minutes of the hour" maintenance window
	freezer.move_to(dt_util.as_utc(datetime(2026, 9, 23, 10, 30, tzinfo=dt_util.get_default_time_zone())))
	FakeClient.login_calls = 0
	FakeClient.schedule_calls = 0
	FakeClient.notifications = []
	FakeClient.notifications_broken = False
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
	device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, USERNAME)})
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
	assert entry.options == {CONF_NOTIFY_SERVICES: ["mobile_app_phone"], CONF_PERSISTENT_NOTIFICATION: True}
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
	button_id = "button.infomentor_send_test_notification"
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
