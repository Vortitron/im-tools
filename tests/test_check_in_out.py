"""Check the live response contract and child-selection safety without an account."""

import asyncio
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "infomentor"))

from infomentor.check_in_out import CheckInOut  # noqa: E402
from infomentor.client import InfoMentorClient  # noqa: E402
from infomentor.exceptions import (  # noqa: E402
	InfoMentorAPIError, InfoMentorAppUnavailableError, InfoMentorAuthError, InfoMentorDataError,
)

DAY = date(2025, 2, 12)
PAYLOAD = {"date": "2025-02-12T00:00:00", "checkedIn": "08:12", "checkedOut": "16:45"}


@pytest.mark.parametrize("day, offset", [(DAY, 1), (date(2026, 7, 1), 2)])
def test_recorded_times_use_school_date_and_dst(day, offset):
	record = CheckInOut.from_response({**PAYLOAD, "date": day.isoformat()}, day)
	assert record.checked_in.date() == day
	assert record.checked_in.hour == 8
	assert record.checked_in.utcoffset() == timedelta(hours=offset)
	assert record.checked_out.hour == 16


@pytest.mark.parametrize("empty", ["", None])
def test_unrecorded_times_are_unknown(empty):
	record = CheckInOut.from_response({**PAYLOAD, "checkedIn": empty, "checkedOut": empty}, DAY)
	assert record.checked_in is None and record.checked_out is None


@pytest.mark.parametrize("payload", [
	{}, {**PAYLOAD, "date": "2025-02-11"}, {**PAYLOAD, "date": None},
	{**PAYLOAD, "checkedIn": "25:00"}, {**PAYLOAD, "checkedOut": "not checked out"},
	{**PAYLOAD, "checkedIn": 837}, {"date": DAY.isoformat(), "checkedIn": "08:12"},
	[],
])
def test_bad_or_wrong_date_responses_are_not_attendance(payload):
	with pytest.raises(InfoMentorDataError):
		CheckInOut.from_response(payload, DAY)


class Response:
	def __init__(self, payload, status=200):
		self.payload, self.status = payload, status

	async def __aenter__(self):
		return self

	async def __aexit__(self, *args):
		return False

	async def json(self, **kwargs):
		return self.payload

	async def text(self):
		return self.payload


def make_client(payload=None, status=200):
	posts = []

	def post(url, **kwargs):
		posts.append((url, kwargs))
		return Response(PAYLOAD if payload is None else payload, status)

	client = InfoMentorClient(session=SimpleNamespace(post=post))
	client.authenticated = True
	client.auth = SimpleNamespace(pupil_ids=["alice", "bob"])
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob", "bob", "alice"])
	client.switch_pupil = AsyncMock(return_value=True)
	return client, posts


def run(coro):
	# Leave pytest-homeassistant's event loop policy alone.
	loop = asyncio.new_event_loop()
	try:
		return loop.run_until_complete(coro)
	finally:
		loop.close()


def test_read_posts_date_verifies_child_and_restores_original():
	client, posts = make_client()
	record = run(client.get_check_in_out("bob", DAY))
	assert record.checked_in.hour == 8
	assert [call.args[0] for call in client.switch_pupil.await_args_list] == ["bob", "alice"]
	assert posts[0][0].endswith("/TimeRegistration/TimeRegistration/GetComments/")
	assert posts[0][1]["data"] == {"date": "2025-02-12T00:00:00"}
	assert posts[0][1]["allow_redirects"] is False


def test_failed_switch_never_reads_previous_child_and_restores():
	client, posts = make_client()
	client.switch_pupil = AsyncMock(side_effect=[False, True])
	client._selected_pupil = AsyncMock(side_effect=["alice", "alice"])
	with pytest.raises(InfoMentorAPIError):
		run(client.get_check_in_out("bob", DAY))
	assert not posts
	assert client.switch_pupil.await_args_list[-1].args == ("alice",)


@pytest.mark.parametrize("status, error_type", [
	(401, InfoMentorAuthError), (403, InfoMentorAppUnavailableError), (500, InfoMentorAPIError),
])
def test_http_failure_restores_original_child(status, error_type):
	client, _ = make_client(status=status)
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob", "alice"])
	with pytest.raises(error_type):
		run(client.get_check_in_out("bob", DAY))
	assert client.switch_pupil.await_args_list[-1].args == ("alice",)


def test_context_change_discards_response():
	client, _ = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob", "alice", "alice"])
	with pytest.raises(InfoMentorDataError):
		run(client.get_check_in_out("bob", DAY))


def test_current_child_needs_no_switch():
	client, posts = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", "alice"])
	assert run(client.get_check_in_out("alice", DAY)).checked_out.minute == 45
	client.switch_pupil.assert_not_awaited()
	assert len(posts) == 1


def test_changed_context_is_restored_even_when_target_was_initially_selected():
	client, _ = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob", "alice"])
	with pytest.raises(InfoMentorDataError):
		run(client.get_check_in_out("alice", DAY))
	client.switch_pupil.assert_awaited_once_with("alice")


def test_unconfirmed_switch_never_requests_comments():
	client, posts = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", "alice", "alice"])
	with pytest.raises(InfoMentorDataError):
		run(client.get_check_in_out("bob", DAY))
	assert not posts


def test_invalid_response_restores_original_child():
	client, _ = make_client(payload={**PAYLOAD, "date": "2025-02-11"})
	with pytest.raises(InfoMentorDataError):
		run(client.get_check_in_out("bob", DAY))
	assert client.switch_pupil.await_args_list[-1].args == ("alice",)


def test_cancellation_restores_original_child():
	client, _ = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", asyncio.CancelledError(), "alice"])
	with pytest.raises(asyncio.CancelledError):
		run(client.get_check_in_out("bob", DAY))
	assert client.switch_pupil.await_args_list[-1].args == ("alice",)


@pytest.mark.parametrize("status, error_type", [
	(401, InfoMentorAuthError), (403, InfoMentorAppUnavailableError),
])
def test_failed_cleanup_preserves_original_error(status, error_type):
	client, _ = make_client(status=status)
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob"])
	client.switch_pupil = AsyncMock(side_effect=[True, False])
	with pytest.raises(error_type):
		run(client.get_check_in_out("bob", DAY))


def test_failed_cleanup_preserves_cancellation():
	client, _ = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", asyncio.CancelledError()])
	client.switch_pupil = AsyncMock(side_effect=[True, False])
	with pytest.raises(asyncio.CancelledError):
		run(client.get_check_in_out("bob", DAY))


def test_failed_cleanup_does_not_publish_successful_read():
	client, _ = make_client()
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob", "bob"])
	client.switch_pupil = AsyncMock(side_effect=[True, False])
	with pytest.raises(InfoMentorAPIError, match="restore original child"):
		run(client.get_check_in_out("bob", DAY))


def test_cleanup_timeout_preserves_authentication_error(monkeypatch):
	client, _ = make_client(status=401)
	client._selected_pupil = AsyncMock(side_effect=["alice", "bob"])

	async def switch(pupil_id):
		if pupil_id == "bob":
			return True
		await asyncio.Event().wait()

	client.switch_pupil = AsyncMock(side_effect=switch)
	monkeypatch.setattr("infomentor.client.CHECK_IN_OUT_RESTORE_TIMEOUT", 0.01)
	with pytest.raises(InfoMentorAuthError):
		run(client.get_check_in_out("bob", DAY))


def test_bootstrap_selection_is_parsed_without_executing_javascript():
	client, _ = make_client()
	bootstrap = {"account": {"pupils": [{"id": "alice", "selected": True}]}}
	client._session = SimpleNamespace(get=lambda *args, **kwargs: Response(
		"<script>IMHome.home.homeData = " + json.dumps(bootstrap) + "; arbitraryJavaScript();</script>"
	))
	assert run(InfoMentorClient._selected_pupil(client)) == "alice"
