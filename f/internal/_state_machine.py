from typing import Literal

# ============================================================================
# STATE MACHINE — Booking Status Transition Validator
# ============================================================================
# AGENTS.md §5.2: Strict state machine with explicit terminal states.
# Single source of truth for booking status transitions.
# ============================================================================

BookingStatus = Literal["pending", "confirmed", "in_service", "completed", "cancelled", "no_show", "rescheduled"]

# ============================================================================
# VALID_TRANSITIONS — Authoritative transition map (AGENTS.md §5.2)
# Terminal states (completed, cancelled, no_show, rescheduled) have empty lists.
# Any mutation outside this matrix is a catastrophic bug.
# ============================================================================
VALID_TRANSITIONS: dict[BookingStatus, list[BookingStatus]] = {
    "pending": ["confirmed", "cancelled", "rescheduled"],
    "confirmed": ["in_service", "cancelled", "rescheduled", "no_show"],
    "in_service": ["completed", "no_show"],
    "completed": [],
    "cancelled": [],
    "no_show": [],
    "rescheduled": [],
}


# ============================================================================
# validate_transition — Go-style error tuple return
# Returns tuple[Exception | None, bool | None]. No exceptions raised.
# ============================================================================
def validate_transition(
    current: BookingStatus,
    next_state: BookingStatus,
) -> tuple[Exception | None, bool | None]:
    allowed = VALID_TRANSITIONS.get(current)
    if allowed is None or next_state not in allowed:
        return (Exception(f"invalid_transition: {current} -> {next_state}"), None)
    return (None, True)
