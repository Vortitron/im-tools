"""Recorded care-session times, distinct from the parent's planned schedule."""

from dataclasses import dataclass
from datetime import date, datetime, time
import re
from zoneinfo import ZoneInfo

from .exceptions import InfoMentorDataError

SCHOOL_TIME_ZONE = ZoneInfo("Europe/Stockholm")


def school_today() -> date:
	"""Return today's date in the Swedish school's time zone."""
	return datetime.now(SCHOOL_TIME_ZONE).date()


@dataclass(frozen=True)
class CheckInOut:
	"""Actual recorded times for one child and one school date."""

	date: date
	checked_in: datetime | None
	checked_out: datetime | None

	@classmethod
	def from_response(cls, payload: dict, requested_date: date) -> "CheckInOut":
		"""Validate the provider's date and HH:mm values; empty means unrecorded."""
		if not isinstance(payload, dict):
			raise InfoMentorDataError("Invalid check-in/out response")
		try:
			response_date = datetime.fromisoformat(payload["date"]).date()
		except (KeyError, TypeError, ValueError) as err:
			raise InfoMentorDataError("Missing or invalid check-in/out date") from err
		if response_date != requested_date:
			raise InfoMentorDataError("Check-in/out response is for another date")

		def timestamp(key: str) -> datetime | None:
			if key not in payload:
				raise InfoMentorDataError("Missing check-in/out field")
			value = payload[key]
			if value in (None, ""):
				return None
			if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
				raise InfoMentorDataError("Invalid recorded check-in/out time")
			return datetime.combine(requested_date, time.fromisoformat(value), SCHOOL_TIME_ZONE)

		return cls(response_date, timestamp("checkedIn"), timestamp("checkedOut"))
