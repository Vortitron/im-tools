"""Constants for the InfoMentor integration."""

from datetime import timedelta

DOMAIN = "infomentor"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Default values
DEFAULT_UPDATE_INTERVAL = timedelta(hours=12)  # Normal update interval when everything is working
DEFAULT_SCAN_INTERVAL = timedelta(hours=12)

# Retry scheduling - simplified and more aggressive
RETRY_INTERVAL_HOURS = 1  # Retry every hour if data is missing or authentication fails
RETRY_INTERVAL_MINUTES_FAST = 15  # Fast retry for immediate issues (first few attempts)
MAX_FAST_RETRIES = 3  # Number of fast retries before switching to hourly
AUTH_BACKOFF_MINUTES = 15  # Reduced backoff time for authentication failures
MAX_AUTH_FAILURES_BEFORE_BACKOFF = 5  # Allow more auth failures before backing off

# Smart retry scheduling
FIRST_ATTEMPT_HOUR = 2  # First attempt at 2 AM
RETRY_INTERVAL_MINUTES = 20  # Retry every 20 minutes
MAX_RETRIES_PER_DAY = 36  # Maximum retries in a day (12 hours worth of 20-minute intervals)

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
SERVICE_FORCE_REFRESH = "force_refresh"
SERVICE_DEBUG_AUTH = "debug_authentication"
SERVICE_CLEANUP_DUPLICATES = "cleanup_duplicate_entities"