"""InfoMentor Python Library for Home Assistant Integration."""

from .client import InfoMentorClient
from .auth import InfoMentorAuth
from .models import NewsItem, TimelineEntry, PupilInfo
from .exceptions import (
	InfoMentorAuthError,
	InfoMentorAPIError,
	InfoMentorConnectionError,
)

__version__ = "1.0.0"
__all__ = [
	"InfoMentorClient",
	"InfoMentorAuth", 
	"NewsItem",
	"TimelineEntry",
	"PupilInfo",
	"InfoMentorAuthError",
	"InfoMentorAPIError", 
	"InfoMentorConnectionError",
] 