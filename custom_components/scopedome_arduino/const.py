"""Constants for the ScopeDome Arduino Card integration."""

from datetime import timedelta

DOMAIN = "scopedome_arduino"
CONF_PASSWORD = "password"
CONF_PORT = "port"
CONF_SENSOR_ACTIVE_LEVEL = "sensor_active_level"
UNKNOWN_LEVEL = "unknown"
SCAN_INTERVAL = timedelta(seconds=15)
HTTP_TIMEOUT = 8
