from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field


class CircuitState(TypedDict):
    service_id: str
    state: Literal["closed", "open", "half-open"]
    failure_count: int
    success_count: int
    failure_threshold: int
    success_threshold: int
    timeout_seconds: int
    opened_at: str | None
    half_open_at: str | None
    last_failure_at: str | None
    last_success_at: str | None
    last_error_message: str | None


class CircuitBreakerResult(TypedDict, total=False):
    allowed: bool
    state: str
    retry_after: float
    message: str
    failure_count: int
    success_count: int
    error_message: str


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    action: Literal["check", "record_success", "record_failure", "reset", "status"]
    service_id: str = Field(min_length=1)
    error_message: str | None = None
