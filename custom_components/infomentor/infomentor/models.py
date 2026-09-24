"""Data models for InfoMentor entities."""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, List


@dataclass
class PupilInfo:
	"""Information about a pupil/student."""
	id: str
	name: Optional[str] = None
	class_name: Optional[str] = None
	school: Optional[str] = None


@dataclass
class NewsItem:
	"""A news item from InfoMentor."""
	id: str
	title: str
	content: str
	published_date: datetime
	author: Optional[str] = None
	category: Optional[str] = None
	pupil_id: Optional[str] = None
	
	def __str__(self) -> str:
		return f"{self.title} - {self.published_date.strftime('%Y-%m-%d')}"


@dataclass
class TimelineEntry:
	"""A timeline entry from InfoMentor."""
	id: str
	title: str
	content: str
	date: datetime
	entry_type: str  # e.g., "assignment", "announcement", "event"
	pupil_id: Optional[str] = None
	author: Optional[str] = None
	
	def __str__(self) -> str:
		return f"{self.title} ({self.entry_type}) - {self.date.strftime('%Y-%m-%d')}"


@dataclass
class AttendanceEntry:
	"""An attendance record."""
	date: datetime
	status: str  # "present", "absent", "late"
	reason: Optional[str] = None
	pupil_id: Optional[str] = None


@dataclass
class Assignment:
	"""An assignment from InfoMentor."""
	id: str
	title: str
	description: str
	due_date: Optional[datetime] = None
	subject: Optional[str] = None
	status: Optional[str] = None  # "submitted", "pending", "graded"
	pupil_id: Optional[str] = None


@dataclass
class TimetableEntry:
	"""A timetable entry for school children."""
	id: str
	title: str
	date: datetime
	subject: Optional[str] = None
	start_time: Optional[time] = None
	end_time: Optional[time] = None
	teacher: Optional[str] = None
	room: Optional[str] = None
	description: Optional[str] = None
	entry_type: Optional[str] = None
	is_all_day: bool = False
	pupil_id: Optional[str] = None
	
	def __str__(self) -> str:
		if self.start_time and self.end_time:
			return f"{self.title} ({self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')})"
		else:
			return f"{self.title} (all day)" if self.is_all_day else self.title


@dataclass 
class TimeRegistrationEntry:
	"""A time registration entry for preschool children and fritids."""
	id: str
	date: datetime
	start_time: Optional[time] = None
	end_time: Optional[time] = None
	status: Optional[str] = None  # "planned", "confirmed", "absent", "pending", "locked", "on_leave"
	comment: Optional[str] = None
	is_locked: bool = False
	is_school_closed: bool = False
	on_leave: bool = False
	can_edit: bool = True
	school_closed_reason: Optional[str] = None
	pupil_id: Optional[str] = None
	registration_type: Optional[str] = None  # New field to store actual type from API
	
	@property
	def type(self) -> str:
		"""Get the registration type for display."""
		if self.is_school_closed:
			return "school_closed"
		elif self.on_leave:
			return "on_leave"
		elif self.registration_type:
			# Use the actual type from API if available
			return self.registration_type
		elif self.status in ["pending", "planned"]:
			return "fritids_pending"
		else:
			# Default based on typical time patterns as fallback
			# Preschool typically has longer hours (08:00-16:00)
			# Fritids typically has shorter hours (12:00-16:00 or similar)
			if self.start_time and self.start_time <= time(9, 0):
				return "förskola"  # Early start suggests preschool
			else:
				return "fritids"   # Later start suggests after-school care
	
	def __str__(self) -> str:
		time_str = ""
		if self.start_time and self.end_time:
			time_str = f" ({self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')})"
		elif self.start_time or self.end_time:
			time_str = f" ({(self.start_time or self.end_time).strftime('%H:%M')})"
		else:
			time_str = " (times TBD)"
		
		status_str = f" [{self.status}]" if self.status else ""
		return f"Time registration - {self.date.strftime('%Y-%m-%d')}{time_str}{status_str}"


@dataclass
class InfoMentorNotification:
	"""A notification from InfoMentor's NotificationApp."""
	id: int
	title: str
	sub_title: str
	date_sent: datetime
	app_type: str
	state: str
	notification_type: str
	url: str
	pupil_im2_id: Optional[int] = None
	pupil_source_id: Optional[str] = None
	currently_selected_pupil: bool = False
	entity_type: Optional[str] = None

	@staticmethod
	def from_dict(data: dict) -> "InfoMentorNotification":
		sent_str = data.get("dateSent") or data.get("orderDate", "")
		try:
			date_sent = datetime.strptime(sent_str, "%Y-%m-%dT%H:%M:%S") if sent_str else datetime.now()
		except (ValueError, TypeError):
			date_sent = datetime.now()

		return InfoMentorNotification(
			id=int(data.get("id", 0)),
			title=data.get("title", ""),
			sub_title=data.get("subTitle", ""),
			date_sent=date_sent,
			app_type=data.get("appType", ""),
			state=data.get("state", ""),
			notification_type=data.get("type", ""),
			url=data.get("url", ""),
			pupil_im2_id=data.get("pupilIM2Id"),
			pupil_source_id=data.get("pupilSourceId"),
			currently_selected_pupil=data.get("currentlySelectedPupil", False),
			entity_type=data.get("entityTypeString"),
		)

	@property
	def is_new(self) -> bool:
		return self.state == "New"

	@property
	def pupil_id(self) -> Optional[str]:
		"""Hub pupil ID, taken from pupilSourceId ("92_V|1806227557|SCHOOL").

		pupilIM2Id is a different numbering and doesn't match the hub pupil IDs.
		"""
		parts = (self.pupil_source_id or "").split("|")
		return parts[1] if len(parts) >= 2 and parts[1] else None

	@property
	def full_url(self) -> str:
		"""Build a complete URL for the notification."""
		base = "https://hub.infomentor.se"
		raw = self.url
		if raw.startswith("http"):
			return raw
		if "#/" in raw:
			# Hub pages are client-side routes; the "#/" must be kept
			return f"{base}/#/{raw.split('#/', 1)[1]}"
		return f"{base}/{raw.lstrip('/')}"

	def url_param(self, name: str) -> Optional[str]:
		"""Query parameter from the notification URL (e.g. eventId)."""
		from urllib.parse import parse_qs, urlparse
		query = urlparse(self.url.split("#", 1)[-1]).query
		values = parse_qs(query).get(name)
		return values[0] if values else None

	@property
	def url_path_id(self) -> Optional[str]:
		"""Trailing numeric ID in the URL path, e.g. the news ID in #/communication/news/2143358."""
		path = self.url.split("?", 1)[0].rstrip("/")
		last = path.rsplit("/", 1)[-1]
		return last if last.isdigit() else None

	def __str__(self) -> str:
		return f"{self.title} ({self.date_sent.strftime('%Y-%m-%d %H:%M')})"


@dataclass
class ScheduleDay:
	"""A complete schedule for a single day."""
	date: datetime
	pupil_id: str
	timetable_entries: List[TimetableEntry]
	time_registrations: List[TimeRegistrationEntry]
	
	@property
	def attended_time_registrations(self) -> List[TimeRegistrationEntry]:
		"""Registrations the child actually attends.

		InfoMentor keeps the planned times on days the school is closed (e.g.
		studiedag) or the child is on leave, so those must not count.
		"""
		return [r for r in self.time_registrations if not r.is_school_closed and not r.on_leave]
	
	@property
	def has_school(self) -> bool:
		"""Check if there are any scheduled activities for this day (school, preschool, or fritids)."""
		return len(self.timetable_entries) > 0 or len(self.attended_time_registrations) > 0
	
	@property
	def has_timetable_entries(self) -> bool:
		"""Check if there are actual school timetable entries for this day."""
		return len(self.timetable_entries) > 0
		
	@property 
	def has_preschool_or_fritids(self) -> bool:
		"""Check if the child attends preschool/fritids this day."""
		return len(self.attended_time_registrations) > 0
		
	@property
	def earliest_start(self) -> Optional[time]:
		"""Get the earliest start time for the day."""
		times = []
		if self.timetable_entries:
			times.extend([entry.start_time for entry in self.timetable_entries if entry.start_time])
		times.extend([entry.start_time for entry in self.attended_time_registrations if entry.start_time])
		return min(times) if times else None
		
	@property 
	def latest_end(self) -> Optional[time]:
		"""Get the latest end time for the day."""
		times = []
		if self.timetable_entries:
			times.extend([entry.end_time for entry in self.timetable_entries if entry.end_time])
		times.extend([entry.end_time for entry in self.attended_time_registrations if entry.end_time])
		return max(times) if times else None 