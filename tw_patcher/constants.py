# RPFM server defaults
RPFM_DEFAULT_PORT = 45127
RPFM_DEFAULT_TIMEOUT = 60  # seconds
RPFM_STARTUP_ATTEMPTS = 10
RPFM_STARTUP_WAIT = 1.0  # seconds between connection retries
RPFM_WS_MAX_SIZE = 50 * 1024 * 1024  # 50 MB WebSocket buffer

# Source mod limits
MAX_SOURCE_MODS = 6

# Network timeouts
HTTP_TIMEOUT = 15  # seconds (Steam API, artwork downloads)
THUMBNAIL_TIMEOUT = 10  # seconds (thumbnail downloads)
PORT_CHECK_TIMEOUT = 2  # seconds (local port connectivity check)
