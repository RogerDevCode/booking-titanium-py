from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any, cast

from f.internal._result import DBClient

from ._orchestrator_models import CanonicalIntent, OrchestratorInput, OrchestratorResult

"""
PRE-FLIGHT
Mission          : Intent normalization and routing mapping.
DB Tables        : NONE
Concurrency Risk : NO
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : NO
Zod Schemas      : NO
"""

LEGACY_INTENT_MAP: dict[str, CanonicalIntent] = {
    "reagendar": "reagendar_cita",
    "consultar_disponible": "ver_disponibilidad",
    "consultar_disponibilidad": "ver_disponibilidad",
    "ver_mis_citas": "mis_citas",
}

AUTHORIZED_INTENTS = [
    "crear_cita",
    "cancelar_cita",
    "reagendar_cita",
    "ver_disponibilidad",
    "mis_citas",
]


def normalize_intent(intent: str) -> CanonicalIntent | None:
    """Maps legacy or relative intent names to canonical ones."""
    mapped = LEGACY_INTENT_MAP.get(intent)
    if mapped:
        return mapped
    if intent in AUTHORIZED_INTENTS:
        return cast("CanonicalIntent", intent)
    return None


# Type alias for handlers
OrchestratorHandler = Callable[
    [DBClient, OrchestratorInput, Mapping[str, Callable[..., Coroutine[Any, Any, Any]]]],
    Awaitable[OrchestratorResult],
]
