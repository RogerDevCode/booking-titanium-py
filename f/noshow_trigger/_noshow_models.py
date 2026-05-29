from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field


class NoShowStats(TypedDict):
    processed: int
    marked: int
    skipped: int
    booking_ids: list[str]


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    lookback_minutes: int = Field(default=30, ge=1)
    dry_run: bool = False


class ProviderRow(BaseModel):
    provider_id: str
