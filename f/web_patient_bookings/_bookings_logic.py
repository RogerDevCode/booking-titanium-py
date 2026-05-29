from datetime import UTC, datetime
from typing import Any

from ..internal._result import DBClient
from ._bookings_models import BookingInfo, BookingsResult, InputSchema

CANCELLABLE_STATUSES = ["pending", "confirmed"]
RESCHEDULABLE_STATUSES = ["pending", "confirmed"]


async def resolve_client_id(db: DBClient, user_id: str) -> str:
    try:
        # Direct lookup
        rows = await db.fetch("SELECT client_id FROM clients WHERE client_id = $1::uuid LIMIT 1", user_id)
        if rows:
            return str(rows[0]["client_id"])

        # Fallback: email match
        rows = await db.fetch(
            "SELECT client_id FROM clients WHERE email = (SELECT email FROM users WHERE user_id = $1::uuid LIMIT 1)",
            user_id,
        )
        if not rows:
            raise RuntimeError(f"client_identity_not_found: userId={user_id}")

        return str(rows[0]["client_id"])
    except Exception as e:
        raise RuntimeError(f"identity_resolution_failed: {e}") from e


async def get_patient_bookings(db: DBClient, client_id: str, input_data: InputSchema) -> BookingsResult:
    try:
        query = """
            SELECT b.booking_id, b.start_time, b.end_time, b.status,
                   b.cancellation_reason,
                   p.name AS provider_name, p.specialty AS provider_specialty,
                   s.name AS service_name
            FROM bookings b
            INNER JOIN providers p ON b.provider_id = p.provider_id
            INNER JOIN services s ON b.service_id = s.service_id
            WHERE b.client_id = $1::uuid
        """
        params: list[Any] = [client_id]

        if input_data.status != "all":
            query += " AND b.status = $2"
            params.append(input_data.status)

        count_query = query.replace(
            "b.booking_id, b.start_time, b.end_time, b.status, b.cancellation_reason, p.name AS provider_name, p.specialty AS provider_specialty, s.name AS service_name",  # noqa: E501
            "COUNT(*)",
        )

        query += f" ORDER BY b.start_time DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
        params.extend([input_data.limit, input_data.offset])

        rows = await db.fetch(query, *params)
        count_rows = await db.fetch(count_query, *params[:-2])
        total = int(count_rows[0]["count"]) if count_rows else 0  # type: ignore[call-overload]

        now = datetime.now(UTC)
        upcoming: list[BookingInfo] = []
        past: list[BookingInfo] = []

        for r in rows:
            st_raw = r["start_time"]
            st: datetime
            if isinstance(st_raw, str):
                st = datetime.fromisoformat(st_raw.replace("Z", "+00:00"))
            elif isinstance(st_raw, datetime):
                st = st_raw
            else:
                st = datetime.now(UTC)

            status = str(r["status"])
            et_raw = r["end_time"]
            et: datetime | str
            if isinstance(et_raw, datetime):
                et = et_raw.isoformat()
            else:
                et = str(et_raw)
            info: BookingInfo = {
                "booking_id": str(r["booking_id"]),
                "start_time": st.isoformat().replace("+00:00", "Z"),
                "end_time": et,
                "status": status,
                "cancellation_reason": str(r["cancellation_reason"]) if r.get("cancellation_reason") else None,
                "provider_name": str(r["provider_name"]) if r.get("provider_name") else None,
                "provider_specialty": str(r["provider_specialty"]) if r.get("provider_specialty") else "General",
                "service_name": str(r["service_name"]) if r.get("service_name") else "Consulta",
                "can_cancel": status in CANCELLABLE_STATUSES,
                "can_reschedule": status in RESCHEDULABLE_STATUSES,
            }

            if st > now:
                upcoming.append(info)
            else:
                past.append(info)

        return {"upcoming": upcoming, "past": past, "total": total}
    except Exception as e:
        raise RuntimeError(f"fetch_bookings_failed: {e}") from e
