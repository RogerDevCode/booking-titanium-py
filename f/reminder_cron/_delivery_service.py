from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..internal._wmill_adapter import run_script

if TYPE_CHECKING:
    from ..reminder_config._config_models import ReminderChannel, ReminderWindow
    from ._reminder_models import ReminderMessage


def dispatch_reminder(
    channel: ReminderChannel,
    recipient_id: str,
    reminder_window: ReminderWindow,
    message: ReminderMessage,
) -> None:
    if channel == "telegram":
        err, _ = run_script(
            "f/telegram_send/main.py",
            {
                "chat_id": recipient_id,
                "text": message.text,
                "mode": "send_message",
                "inline_buttons_json": json.dumps(
                    [[button.model_dump() for button in row] for row in message.inline_buttons]
                ),
            },
        )
        if err is not None:
            raise RuntimeError(err)
        return

    err, _ = run_script(
        "f/gmail_send/main.py",
        {
            "recipient_email": recipient_id,
            "message_type": f"reminder_{reminder_window}",
            "booking_details": message.booking_details.model_dump(),
        },
    )
    if err is not None:
        raise RuntimeError(err)
    return
