"""Constants for the ScopeDome Arduino Card integration."""

from datetime import timedelta

DOMAIN = "scopedome_arduino"
CONF_PASSWORD = "password"
CONF_PORT = "port"
CONF_SENSOR_ACTIVE_LEVEL = "sensor_active_level"
CONF_HOME_ACTIVE_LEVEL = "home_active_level"
CONF_RAIN_ACTIVE_LEVEL = "rain_active_level"
CONF_ROTATION_STEP = "rotation_step_pulses"
CONF_ENCODER_COUNTS_PER_TURN = "encoder_counts_per_turn"
CONF_HOME_ENCODER_COUNT = "home_encoder_count"
CONF_HOME_AZIMUTH = "home_azimuth"
CONF_ENCODER_DIRECTION = "encoder_direction"
CONF_PARK_AZIMUTH = "park_azimuth"
CONF_CLOUD_INDEX_THRESHOLD = "cloud_index_threshold"
UNKNOWN_LEVEL = "unknown"
SCAN_INTERVAL = timedelta(seconds=15)
HTTP_TIMEOUT = 8
