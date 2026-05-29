from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class LockInfo(TypedDict):
    lock_id: str
    lock_key: str
    owner_token: str
    provider_id: str
    start_time: str
    acquired_at: str
    expires_at: str


class LockResult(TypedDict, total=False):
    acquired: bool
    released: bool
    locked: bool
    cleaned: int
    lock: LockInfo
    reason: str
    owner: str
    expires_at: str


class LockRow(TypedDict):
    lock_id: str
    lock_key: str
    owner_token: str
    provider_id: str
    start_time: object
    acquired_at: object
    expires_at: object


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["acquire", "release", "check", "cleanup"]
    lock_key: str = Field(min_length=1)
    owner_token: str | None = None
    provider_id: str
    start_time: str | None = None
    ttl_seconds: int = Field(default=30, ge=1, le=3600)
