from __future__ import annotations

from typing import Literal, Required, TypedDict

from pydantic import BaseModel, ConfigDict, Field

"""
PRE-FLIGHT
Mission          : Orchestrator models for input validation and internal data structures.
DB Tables        : NONE
Concurrency Risk : NO
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : NO
Zod Schemas      : YES — Pydantic equivalent of InputSchema
"""

CanonicalIntent = Literal[
    "crear_cita",
    "cancelar_cita",
    "reagendar_cita",
    "ver_disponibilidad",
    "mis_citas",
]

ExtendedIntent = Literal[
    "crear_cita",
    "cancelar_cita",
    "reagendar_cita",
    "ver_disponibilidad",
    "mis_citas",
    "reagendar",
    "consultar_disponible",
    "consultar_disponibilidad",
    "ver_mis_citas",
]


class OrchestratorInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    tenant_id: str | None = None
    intent: str
    entities: dict[str, str | None] = Field(default_factory=dict)
    client_id: str | None = None
    provider_id: str | None = None
    service_id: str | None = None
    booking_id: str | None = None
    date: str | None = None
    time: str | None = None
    notes: str | None = None
    channel: Literal["telegram", "web", "api"] = "api"
    telegram_chat_id: str | None = None
    telegram_name: str | None = None


class OrchestratorResult(TypedDict, total=False):
    action: Required[str]
    success: Required[bool]
    message: Required[str]
    data: object
    follow_up: str | None
    inline_buttons: list[list[dict[str, str]]] | None
    nextState: object | None
    nextDraft: object | None


class ResolvedContext(TypedDict):
    tenantId: str
    clientId: str | None
    providerId: str | None
    serviceId: str | None
    date: str | None
    time: str | None


class AvailabilitySlot(TypedDict):
    start: str
    available: bool


class AvailabilityData(TypedDict, total=False):
    is_blocked: bool
    block_reason: str | None
    total_available: int
    slots: list[AvailabilitySlot]


class BookingRow(TypedDict):
    start_time: str
    provider_name: str
    specialty: str
    service_name: str
