"""Data models for InfoMentor entities."""

from dataclasses import dataclass
from datetime import datetime
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