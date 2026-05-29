from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._agenda_models import AgendaInput, AgendaRow


async def get_provider_agenda(db: DBClient, input_data: AgendaInput) -> list[AgendaRow]:
    # 1. Base Query
    sql = """
        SELECT b.booking_id, b.status, b.start_time, b.end_time,
               c.name as client_name, c.phone as client_phone,
               s.name as service_name
        FROM bookings b
        JOIN clients c ON c.client_id = b.client_id
        JOIN services s ON s.service_id = b.service_id
        WHERE b.provider_id = $1::uuid
          AND b.start_time::date = $2::date
          AND b.status NOT IN ('cancelled', 'rescheduled')
        ORDER BY b.start_time ASC
    """

    rows = await db.fetch(sql, input_data.provider_id, input_data.target_date)

    res: list[AgendaRow] = []
    for r_raw in rows:
        # Handle both asyncpg Record and standard dict
        r = dict(r_raw)

        st_raw = r.get("start_time")
        et_raw = r.get("end_time")

        if not isinstance(st_raw, datetime) or not isinstance(et_raw, datetime):
            # Fallback for string dates in some environments/mocks
            st = datetime.fromisoformat(str(st_raw).replace("Z", "+00:00")) if st_raw else datetime.now(UTC)
            et = datetime.fromisoformat(str(et_raw).replace("Z", "+00:00")) if et_raw else datetime.now(UTC)
        else:
            st = st_raw
            et = et_raw

        res.append(
            {
                "booking_id": str(r.get("booking_id", "")),
                "status": str(r.get("status", "")),
                "start_time": st.isoformat(),
                "end_time": et.isoformat(),
                "client_name": str(r.get("client_name", "Desconocido")),
                "client_phone": str(r.get("client_phone")) if r.get("client_phone") else None,
                "service_name": str(r.get("service_name", "Consulta")),
            }
        )

    return res
