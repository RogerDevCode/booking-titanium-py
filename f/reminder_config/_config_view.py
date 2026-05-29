from __future__ import annotations

from ._config_models import InlineButton, ReminderConfigView, ReminderPreferences


def _window_button(enabled: bool, label: str, callback_data: str) -> InlineButton:
    icon = "☑️" if enabled else "☐"
    return InlineButton(text=f"{icon} {label}", callback_data=callback_data)


def build_config_view(preferences: ReminderPreferences) -> ReminderConfigView:
    telegram_icon = "✅" if preferences.channels.telegram else "❌"
    email_icon = "✅" if preferences.channels.email else "❌"

    return ReminderConfigView(
        message="🔔 *Recordatorios*\n\nToca para activar/desactivar:",
        inline_buttons=[
            [
                InlineButton(text=f"📱 Telegram {telegram_icon}", callback_data="rem:ch:telegram"),
                InlineButton(text=f"📧 Email {email_icon}", callback_data="rem:ch:email"),
            ],
            [
                _window_button(preferences.windows.w_1day, "1 día antes", "rem:w:1day"),
                _window_button(preferences.windows.w_24h, "24 horas", "rem:w:24h"),
            ],
            [
                _window_button(preferences.windows.w_12h, "12 horas", "rem:w:12h"),
                _window_button(preferences.windows.w_6h, "6 horas", "rem:w:6h"),
            ],
            [
                _window_button(preferences.windows.w_2h, "2 horas", "rem:w:2h"),
                _window_button(preferences.windows.w_1h, "1 hora", "rem:w:1h"),
            ],
            [_window_button(preferences.windows.w_30min, "30 minutos", "rem:w:30min")],
            [
                InlineButton(text="🔕 Desactivar todo", callback_data="rem:off"),
                InlineButton(text="✅ Activar todo", callback_data="rem:all"),
            ],
            [InlineButton(text="« Menú", callback_data="rem:back")],
        ],
    )
