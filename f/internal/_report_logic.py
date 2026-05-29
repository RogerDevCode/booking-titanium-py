# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "asyncpg>=0.30.0",
# ]
# ///
from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import Final, TypedDict, cast

from ._config import DEFAULT_TIMEZONE
from ._wmill_adapter import log

MODULE: Final[str] = "report_logic"


class ReportData(TypedDict):
    text: str
    inline_buttons: list[list[dict[str, str]]] | None
    total_count: int
    has_more: bool


async def generate_booking_report(
    client_id: str, pg_url: str, page: int = 1, page_size: int = 10, session_id: str | None = None
) -> ReportData | None:
    """Generates a formatted booking report for the last year with pagination."""
    from ._db_client import create_db_client

    db = await create_db_client(pg_url)
    try:
        offset = (page - 1) * page_size
        one_year_ago = datetime.now(UTC) - timedelta(days=365)

        # 1. Get total count for the year
        total_row = await db.fetchrow(
            """
            SELECT COUNT(*) as total
            FROM bookings
            WHERE client_id = $1::uuid
              AND start_time >= $2
            """,
            client_id,
            one_year_ago,
        )
        total_count = int(cast("int", total_row["total"])) if total_row else 0

        if total_count == 0:
            return {
                "text": "📊 *Reporte de Actividad*\n\nNo tienes registros de citas en el último año.",
                "inline_buttons": None,
                "total_count": 0,
                "has_more": False,
            }

        # 2. Fetch page of bookings
        rows = await db.fetch(
            """
            SELECT
                b.start_time,
                b.status,
                p.name AS provider_name,
                s.name AS service_name,
                COALESCE(tz.name, $3) AS tz_name
            FROM bookings b
            JOIN providers p ON p.provider_id = b.provider_id
            JOIN services s ON s.service_id = b.service_id
            LEFT JOIN timezones tz ON tz.id = p.timezone_id
            WHERE b.client_id = $1::uuid
              AND b.start_time >= $2
            ORDER BY b.start_time DESC
            LIMIT $4 OFFSET $5
            """,
            client_id,
            one_year_ago,
            DEFAULT_TIMEZONE,
            page_size,
            offset,
        )

        lines: list[str] = [f"📊 *Reporte de Actividad (Pág. {page})*\n"]

        for r in rows:
            st = cast("datetime", r["start_time"])
            if not st.tzinfo:
                st = st.replace(tzinfo=UTC)
            row_tz = zoneinfo.ZoneInfo(str(r["tz_name"]))
            local_st = st.astimezone(row_tz)

            date_str = local_st.strftime("%d/%m/%Y")
            time_str = local_st.strftime("%H:%M")
            status = str(r["status"])
            status_icon = "✅" if status == "confirmed" else "❌" if status == "cancelled" else "🕒"

            lines.append(f"{status_icon} *{date_str} {time_str}*\n👨‍⚕️ {r['provider_name']}\n📋 {r['service_name']}\n")

        has_more = (offset + page_size) < total_count
        buttons: list[list[dict[str, str]]] = []
        suffix = f"|{session_id}" if session_id else ""

        if has_more:
            buttons.append([{"text": "➡️ Ver más", "callback_data": f"cmd:reporte:p:{page + 1}{suffix}"}])

        return {
            "text": "\n".join(lines),
            "inline_buttons": buttons if buttons else None,
            "total_count": total_count,
            "has_more": has_more,
        }

    except Exception as e:
        log("REPORT_GENERATION_ERROR", error=str(e), client_id=client_id, module=MODULE)
        return None
    finally:
        await db.close()
