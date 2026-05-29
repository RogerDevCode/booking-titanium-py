class TitaniumError(Exception):
    """Base exception for all Titanium Booking Engine errors."""
    pass

class FSMError(TitaniumError):
    """Raised when an invalid FSM transition is attempted."""
    pass

class DatabaseError(TitaniumError):
    """Raised when a database operation fails."""
    pass

class BookingConflictError(TitaniumError):
    """Raised when a booking slot is already taken."""
    pass

class ExternalServiceError(TitaniumError):
    """Raised when an external API (Telegram, OpenAI) fails."""
    pass
