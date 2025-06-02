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
class ScheduleDay:
	"""A complete schedule for a single day."""
	date: datetime
	pupil_id: str
	timetable_entries: List[TimetableEntry]
	time_registrations: List[TimeRegistrationEntry]
	
	@property
	def has_school(self) -> bool:
		"""Check if there are any scheduled activities for this day (school, preschool, or fritids)."""
		return len(self.timetable_entries) > 0 or len(self.time_registrations) > 0
	
	@property
	def has_timetable_entries(self) -> bool:
		"""Check if there are actual school timetable entries for this day."""
		return len(self.timetable_entries) > 0
		
	@property 
	def has_preschool_or_fritids(self) -> bool:
		"""Check if there are any time registrations for this day."""
		return len(self.time_registrations) > 0
		
	@property
	def earliest_start(self) -> Optional[time]:
		"""Get the earliest start time for the day."""
		times = []
		if self.timetable_entries:
			times.extend([entry.start_time for entry in self.timetable_entries])
		if self.time_registrations:
			times.extend([entry.start_time for entry in self.time_registrations if entry.start_time])
		return min(times) if times else None
		
	@property 
	def latest_end(self) -> Optional[time]:
		"""Get the latest end time for the day."""
		times = []
		if self.timetable_entries:
			times.extend([entry.end_time for entry in self.timetable_entries])
		if self.time_registrations:
			times.extend([entry.end_time for entry in self.time_registrations if entry.end_time])
		return max(times) if times else None 