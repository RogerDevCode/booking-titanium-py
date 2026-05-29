from __future__ import annotations

import contextlib
import zoneinfo
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from f.internal._config import DEFAULT_TIMEZONE
from f.internal._result import DBClient, with_tenant_context

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    from f.booking_orchestrator._orchestrator_models import OrchestratorInput, OrchestratorResult

"""
PRE-FLIGHT
Mission          : Fetch and format client bookings.
DB Tables Used   : bookings, providers, services
Concurrency Risk : NO
GCal Calls       : NO
Idempotency Key  : NO
RLS Tenant ID    : YES
Zod Schemas      : NO
"""


async def handle_get_my_bookings(
    conn: DBClient, input_data: OrchestratorInput, delegates: Mapping[str, Callable[..., Coroutine[Any, Any, Any]]]
) -> OrchestratorResult:
    client_id = input_data.client_id
    tenant_id = input_data.tenant_id

    if not client_id or not tenant_id:
        raise RuntimeError("Falta identificación de paciente o establecimiento.")

    async def operation() -> list[dict[str, object]]:
        # Get UI preference for limits
        prefs_row = await conn.fetchrow(
            "SELECT ui_preferences->>'max_bookings_per_query' as max_b"
            " FROM providers WHERE provider_id = $1::uuid LIMIT 1",
            tenant_id,
        )
        limit = 20
        if prefs_row and prefs_row["max_b"]:
            with contextlib.suppress(ValueError):
                limit = int(str(prefs_row["max_b"]))

        rows = await conn.fetch(
            """
            SELECT b.booking_id, b.status, b.start_time,
                   p.name as provider_name, s.name as service_name
            FROM bookings b
            JOIN providers p ON p.provider_id = b.provider_id
            JOIN services s ON s.service_id = b.service_id
            WHERE b.client_id = $1::uuid
              AND b.status NOT IN ('cancelled', 'no_show', 'rescheduled')
              AND b.start_time >= NOW()
            ORDER BY b.start_time ASC LIMIT $2
            """,
            client_id,
            limit,
        )
        return rows

    rows = await with_tenant_context(conn, tenant_id, operation)

    tz = zoneinfo.ZoneInfo(DEFAULT_TIMEZONE)
    lines: list[str] = []
    for r in rows:
        st = r["start_time"]
        if isinstance(st, str):
            dt = datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(tz)
        elif isinstance(st, datetime):
            dt = st.astimezone(tz)
        else:
            continue

        provider_name = cast("str", r.get("provider_name", "Desconocido"))
        service_name = cast("str", r.get("service_name", "Servicio"))
        fmt_str = dt.strftime("%d/%m %H:%M")
        lines.append(f"• {fmt_str}hs - {provider_name}: {service_name}")

    msg_body = "\n".join(lines)
    res_data: OrchestratorResult = {
        "action": "mis_citas",
        "success": True,
        "data": rows,
        "message": f"📋 Tus próximas citas:\n{msg_body}" if lines else "📋 No tienes próximas citas.",
        "follow_up": input_data.notes,
    }
    return res_data
