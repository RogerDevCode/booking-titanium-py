from __future__ import annotations

import os
from typing import Final

# ============================================================================
# CONFIG — Single Source of Truth for all constants and configuration
# ============================================================================

# ─── Retry Configuration
MAX_RETRIES: Final[int] = 3
RETRY_BACKOFF_BASE_MS: Final[int] = 500
RETRY_BACKOFF_MULTIPLIER: Final[int] = 2
MAX_GCAL_RETRIES: Final[int] = 10

# ─── Timeout Configuration
TIMEOUT_GCAL_API_MS: Final[int] = 15000
TIMEOUT_TELEGRAM_API_MS: Final[int] = 10000
TIMEOUT_TELEGRAM_CALLBACK_MS: Final[int] = 5000
TIMEOUT_GMAIL_API_MS: Final[int] = 15000
TIMEOUT_DB_QUERY_MS: Final[int] = 30000

# ─── Input Limits
MAX_INPUT_LENGTH: Final[int] = 500
MAX_LLM_RESPONSE_LENGTH: Final[int] = 2000
MAX_FOLLOW_UP_LENGTH: Final[int] = 200
MAX_TELEGRAM_CALLBACK_DATA_BYTES: Final[int] = 64
MAX_CANCELLATION_REASON_LENGTH: Final[int] = 500

# ─── Booking Limits
MAX_BOOKINGS_PER_QUERY: Final[int] = 20
MAX_SLOTS_DISPLAYED: Final[int] = 10

# ─── GCal Configuration
GCAL_BASE_URL: Final[str] = "https://www.googleapis.com/calendar/v3"
GCAL_REMINDER_24H_MIN: Final[int] = 1440
GCAL_REMINDER_2H_MIN: Final[int] = 120
GCAL_REMINDER_30MIN_MIN: Final[int] = 30

# ─── Status Constants
BOOKING_STATUS: Final[dict[str, str]] = {
    "PENDING": "pending",
    "CONFIRMED": "confirmed",
    "IN_SERVICE": "in_service",
    "COMPLETED": "completed",
    "CANCELLED": "cancelled",
    "NO_SHOW": "no_show",
    "RESCHEDULED": "rescheduled",
}

# ─── Locale Configuration
DEFAULT_TIMEZONE: Final[str] = "America/Santiago"


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"CONFIGURATION_ERROR: Required environment variable {name} is not set.")
    return val


def require_database_url() -> str:
    return require_env("DATABASE_URL")
