"""Constants for the Aladdin Connect Homebridge port."""

DOMAIN = "aladdin_connect_cloud"
NAME = "Aladdin Connect Cloud"

API_BASE_URL = "https://api.smartgarage.systems"
AUTH_URL = "https://cognito-idp.us-east-2.amazonaws.com"
# App credentials from the Apache-2.0 Homebridge implementation. These are
# Cognito client credentials, not a user's password or a device-local key.
AUTH_CLIENT_ID = "27iic8c3bvslqngl3hso83t74b"
AUTH_CLIENT_SECRET = "7bokto0ep96055k42fnrmuth84k7jdcjablestb7j53o8lp63v5"

CONF_SHOW_SHARED = "show_shared"
CONF_IGNORED_DOORS = "ignored_doors"
CONF_BATTERY_LOW_LEVEL = "battery_low_level"
DEFAULT_POLL_INTERVAL = 15
DEFAULT_BATTERY_LOW_LEVEL = 15
MOVING_POLL_INTERVAL = 5
COMMAND_TRACKING_SECONDS = 90
REQUEST_TIMEOUT = 10
