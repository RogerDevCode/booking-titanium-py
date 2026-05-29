from __future__ import annotations

from ._config_models import (
    ChannelPreferences,
    ReminderChannel,
    ReminderPreferences,
    ReminderWindow,
    WindowPreferences,
)

DEFAULT_PREFERENCES = ReminderPreferences(
    channels=ChannelPreferences(telegram=True, email=True),
    windows=WindowPreferences(
        w_1day=True,
        w_24h=True,
        w_12h=False,
        w_6h=False,
        w_2h=True,
        w_1h=False,
        w_30min=True,
    ),
)


def default_preferences() -> ReminderPreferences:
    return DEFAULT_PREFERENCES.model_copy(deep=True)


def parse_preferences_payload(raw_payload: dict[str, object] | None) -> ReminderPreferences:
    if raw_payload is None:
        return default_preferences()

    if "channels" in raw_payload or "windows" in raw_payload:
        return ReminderPreferences.model_validate(raw_payload)

    # Compatibility adapter for the legacy flat schema.
    return ReminderPreferences(
        channels=ChannelPreferences(
            telegram=bool(
                raw_payload.get("telegram_24h", True)
                or raw_payload.get("telegram_2h", True)
                or raw_payload.get("telegram_30min", True)
            ),
            email=bool(raw_payload.get("gmail_24h", True) or raw_payload.get("email_24h", True)),
        ),
        windows=WindowPreferences(
            w_1day=True,
            w_24h=bool(raw_payload.get("telegram_24h", True) or raw_payload.get("email_24h", True)),
            w_12h=False,
            w_6h=False,
            w_2h=bool(raw_payload.get("telegram_2h", True) or raw_payload.get("email_2h", True)),
            w_1h=False,
            w_30min=bool(raw_payload.get("telegram_30min", True) or raw_payload.get("email_30min", True)),
        ),
    )


def toggle_channel(preferences: ReminderPreferences, channel: ReminderChannel) -> ReminderPreferences:
    updated = preferences.model_copy(deep=True)
    match channel:
        case "telegram":
            updated.channels.telegram = not updated.channels.telegram
        case "email":
            updated.channels.email = not updated.channels.email
    return updated


def toggle_window(preferences: ReminderPreferences, window: ReminderWindow) -> ReminderPreferences:
    updated = preferences.model_copy(deep=True)
    match window:
        case "1day":
            updated.windows.w_1day = not updated.windows.w_1day
        case "24h":
            updated.windows.w_24h = not updated.windows.w_24h
        case "12h":
            updated.windows.w_12h = not updated.windows.w_12h
        case "6h":
            updated.windows.w_6h = not updated.windows.w_6h
        case "2h":
            updated.windows.w_2h = not updated.windows.w_2h
        case "1h":
            updated.windows.w_1h = not updated.windows.w_1h
        case "30min":
            updated.windows.w_30min = not updated.windows.w_30min
    return updated


def deactivate_all(preferences: ReminderPreferences) -> ReminderPreferences:
    updated = preferences.model_copy(deep=True)
    updated.channels.telegram = False
    updated.channels.email = False
    updated.windows = WindowPreferences(
        w_1day=False,
        w_24h=False,
        w_12h=False,
        w_6h=False,
        w_2h=False,
        w_1h=False,
        w_30min=False,
    )
    return updated


def activate_all() -> ReminderPreferences:
    return default_preferences()
