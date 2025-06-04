"""Constants for the InfoMentor integration."""

from datetime import timedelta

DOMAIN = "infomentor"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Default values
DEFAULT_UPDATE_INTERVAL = timedelta(hours=12)  # Update twice daily to minimize API load and avoid rate limiting
DEFAULT_SCAN_INTERVAL = timedelta(hours=12)

# Sensor types
SENSOR_NEWS = "news"
SENSOR_TIMELINE = "timeline"
SENSOR_PUPIL_COUNT = "pupil_count"
SENSOR_SCHEDULE = "schedule"
SENSOR_TODAY_SCHEDULE = "today_schedule"
SENSOR_TOMORROW_SCHEDULE = "tomorrow_schedule"
SENSOR_HAS_SCHOOL_TODAY = "has_school_today"
SENSOR_HAS_PRESCHOOL_TODAY = "has_preschool_today"
SENSOR_HAS_SCHOOL_TOMORROW = "has_school_tomorrow"
SENSOR_DASHBOARD = "dashboard"

# Attributes
ATTR_PUPIL_ID = "pupil_id"
ATTR_PUPIL_NAME = "pupil_name"
ATTR_AUTHOR = "author"
ATTR_PUBLISHED_DATE = "published_date"
ATTR_ENTRY_TYPE = "entry_type"
ATTR_CONTENT = "content"
ATTR_START_TIME = "start_time"
ATTR_END_TIME = "end_time"
ATTR_SUBJECT = "subject"
ATTR_TEACHER = "teacher"
ATTR_CLASSROOM = "classroom"
ATTR_SCHEDULE_TYPE = "schedule_type"
ATTR_STATUS = "status"
ATTR_EARLIEST_START = "earliest_start"
ATTR_LATEST_END = "latest_end"

# Event types
EVENT_NEW_NEWS = f"{DOMAIN}_new_news"
EVENT_NEW_TIMELINE = f"{DOMAIN}_new_timeline"
EVENT_SCHEDULE_UPDATED = f"{DOMAIN}_schedule_updated"

# Services
SERVICE_REFRESH_DATA = "refresh_data"
SERVICE_SWITCH_PUPIL = "switch_pupil"