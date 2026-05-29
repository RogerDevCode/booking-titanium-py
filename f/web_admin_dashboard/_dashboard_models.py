from typing import TypedDict

from pydantic import BaseModel, ConfigDict


class AdminDashboardResult(TypedDict):
    total_users: int
    total_bookings: int
    total_revenue_cents: int
    no_show_rate: str
    active_providers: int
    pending_bookings: int


class InputSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    admin_user_id: str
