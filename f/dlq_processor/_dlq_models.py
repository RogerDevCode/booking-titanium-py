from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class DLQEntry(TypedDict):
    dlq_id: int
    booking_id: str | None
    provider_id: str | None
    service_id: str | None
    failure_reason: str
    last_error_message: str
    last_error_stack: str | None
    original_payload: dict[str, object]
    idempotency_key: str
    status: Literal["pending", "resolved", "discarded"]
    created_at: str
    updated_at: str
    resolved_at: str | None
    resolved_by: str | None
    resolution_notes: str | None


class DLQListResult(TypedDict):
    entries: list[DLQEntry]
    total: int


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    action: Literal["list", "retry", "resolve", "discard", "status"]
    dlq_id: int | None = None
    status_filter: str | None = None
    resolution_notes: str | None = None
    resolved_by: str | None = None
    max_retries: int = Field(default=10, ge=1, le=20)
