from datetime import datetime

from ..internal._result import DBClient
from ._provider_dashboard_models import AgendaItem, DashboardResult, InputSchema, ProviderStats


async def fetch_provider_dashboard(db: DBClient, input_data: InputSchema) -> DashboardResult:
    try:
        # 1. Resolve Provider and Timezone
        provider_rows = await db.fetch(
            """
            SELECT p.provider_id, p.name, p.specialty, t.name as tz_name
            FROM providers p
            LEFT JOIN timezones t ON t.id = p.timezone_id
            WHERE p.provider_id = $1::uuid
               OR p.email = (SELECT email FROM users WHERE user_id = $1::uuid LIMIT 1)
            LIMIT 1
            """,
            input_data.provider_user_id,
        )

        if not provider_rows:
            raise RuntimeError("Provider record not found")

        p = provider_rows[0]
        p_id = str(p["provider_id"])
        p_name = str(p["name"])
        p_spec = str(p["specialty"])
        p_tz = str(p["tz_name"]) if p["tz_name"] else "UTC"

        # 2. Fetch Agenda
        import zoneinfo

        tz = zoneinfo.ZoneInfo(p_tz)
        target_date = input_data.date or datetime.now(tz).date().isoformat()

        agenda_rows = await db.fetch(
            """
            SELECT b.booking_id, b.start_time, b.end_time, b.status,
                   COALESCE(c.name, '') as client_name,
                   s.name as service_name
            FROM bookings b
            INNER JOIN clients c ON b.client_id = c.client_id
            INNER JOIN services s ON b.service_id = s.service_id
            WHERE b.provider_id = $1::uuid
              AND b.start_time::date = $2::date
              AND b.status NOT IN ('cancelled', 'rescheduled')
            ORDER BY b.start_time ASC
            """,
            p_id,
            target_date,
        )

        agenda: list[AgendaItem] = [
            {
                "booking_id": str(r["booking_id"]),
                "client_name": str(r["client_name"]),
                "client_email": None,
                "service_name": str(r["service_name"]),
                "start_time": r["start_time"].isoformat()
                if isinstance(r["start_time"], datetime)
                else str(r["start_time"]),
                "end_time": r["end_time"].isoformat() if isinstance(r["end_time"], datetime) else str(r["end_time"]),
                "status": str(r["status"]),
            }
            for r in agenda_rows
        ]

        # 3. Monthly Stats
        stats_rows = await db.fetch(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'completed') as month_completed,
              COUNT(*) FILTER (WHERE status = 'no_show') as month_no_show,
              COUNT(*) as month_total
            FROM bookings
            WHERE provider_id = $1::uuid
              AND DATE_TRUNC('month', start_time) = DATE_TRUNC('month', CURRENT_DATE)
            """,
            p_id,
        )

        comp = 0
        ns = 0
        total = 0
        if stats_rows:
            s = stats_rows[0]
            comp = int(s["month_completed"])  # type: ignore[call-overload]
            ns = int(s["month_no_show"])  # type: ignore[call-overload]
            total = int(s["month_total"])  # type: ignore[call-overload]

        rate = f"{(comp / (comp + ns) * 100):.1f}" if (comp + ns) > 0 else "0.0"

        stats: ProviderStats = {
            "today_total": len(agenda),
            "month_total": total,
            "month_completed": comp,
            "month_no_show": ns,
            "attendance_rate": rate,
        }

        return {"provider_id": p_id, "provider_name": p_name, "specialty": p_spec, "agenda": agenda, "stats": stats}

    except Exception as e:
        raise RuntimeError(f"dashboard_failed: {e}") from e
