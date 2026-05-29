from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class InlineButton(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str
    callback_data: str


class ChannelPreferences(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    telegram: bool
    email: bool


class WindowPreferences(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    w_1day: bool  # día anterior a las 08:00
    w_24h: bool
    w_12h: bool
    w_6h: bool
    w_2h: bool
    w_1h: bool
    w_30min: bool


class ReminderPreferences(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    channels: ChannelPreferences
    windows: WindowPreferences


ReminderChannel = Literal["telegram", "email"]
ReminderWindow = Literal["1day", "24h", "12h", "6h", "2h", "1h", "30min"]
ReminderConfigAction = Literal["show", "toggle_channel", "toggle_window", "deactivate_all", "activate_all", "back"]


class ReminderConfigView(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    message: str
    inline_buttons: list[list[InlineButton]]


class ReminderConfigResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    message: str
    inline_buttons: list[list[InlineButton]]
    preferences: ReminderPreferences


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: ReminderConfigAction
    client_id: str
    channel: ReminderChannel | None = None
    window: ReminderWindow | None = None
