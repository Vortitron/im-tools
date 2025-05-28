"""Constants for the InfoMentor integration."""

from datetime import timedelta

DOMAIN = "infomentor"

# Configuration
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Default values
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=15)
DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)

# Sensor types
SENSOR_NEWS = "news"
SENSOR_TIMELINE = "timeline"
SENSOR_PUPIL_COUNT = "pupil_count"

# Attributes
ATTR_PUPIL_ID = "pupil_id"
ATTR_PUPIL_NAME = "pupil_name"
ATTR_AUTHOR = "author"
ATTR_PUBLISHED_DATE = "published_date"
ATTR_ENTRY_TYPE = "entry_type"
ATTR_CONTENT = "content"

# Event types
EVENT_NEW_NEWS = f"{DOMAIN}_new_news"
EVENT_NEW_TIMELINE = f"{DOMAIN}_new_timeline"

# Services
SERVICE_REFRESH_DATA = "refresh_data"
SERVICE_SWITCH_PUPIL = "switch_pupil"