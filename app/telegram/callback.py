from __future__ import annotations
from dataclasses import dataclass

_SEP: str = ":"
_VER: str = "v"


@dataclass(slots=True, frozen=True)
class CallbackPayload:
    version: int
    action: str
    value: str


def encode(version: int, action: str, value: str) -> str:
    """
    Encode a versioned callback_data string.

    Args:
        version: Current conversation state version from ConversationState.version
        action:  Intent identifier. Example: "select_specialty", "confirm_booking"
        value:   Payload value. Example: "cardiology", "slot_42", "back"

    Returns:
        Versioned string ready for InlineKeyboardButton.callback_data
        Example: "v3:select_specialty:cardiology"

    Rules:
        - MUST use state.version at the moment of keyboard construction
        - MUST be called AFTER transition_to() so version is already incremented
        - value MUST NOT contain ":" character
    """
    return f"{_VER}{version}{_SEP}{action}{_SEP}{value}"


def decode(raw: str) -> CallbackPayload | None:
    """
    Decode a versioned callback_data string.

    Args:
        raw: The callback_data string received from Telegram.

    Returns:
        CallbackPayload if valid format, None if malformed or legacy format.

    Rules:
        - Returns None for ANY malformed input — never raises
        - Caller is responsible for handling None (discard the callback)
    """
    parts = raw.split(_SEP, 2)
    if len(parts) != 3:
        return None
    prefix, action, value = parts
    if not prefix.startswith(_VER):
        return None
    try:
        version = int(prefix[1:])
    except ValueError:
        return None
    return CallbackPayload(version=version, action=action, value=value)
