from ..internal._result import DBClient
from ..internal._state_machine import validate_transition


class BookingRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def find_expired_confirmed(self, lookback_minutes: int) -> list[str]:
        try:
            rows = await self.db.fetch(
                """
                SELECT booking_id FROM bookings
                WHERE status = 'confirmed'
                  AND end_time < (NOW() - ($1 || ' minutes')::interval)
                ORDER BY end_time ASC
                LIMIT 100
                """,
                str(lookback_minutes),
            )
            return [str(r["booking_id"]) for r in rows]
        except Exception as e:
            raise RuntimeError(f"find_expired_failed: {e}") from e

    async def mark_as_no_show(self, booking_id: str) -> bool:
        err_trans, _ = validate_transition("confirmed", "no_show")
        if err_trans:
            raise RuntimeError(str(err_trans))

        try:
            # Atomic update
            await self.db.execute(
                "UPDATE bookings SET status = 'no_show', updated_at = NOW() WHERE booking_id = $1::uuid", booking_id
            )
            await self.db.execute(
                """
                INSERT INTO booking_audit (booking_id, from_status, to_status, changed_by, reason)
                VALUES ($1::uuid, 'confirmed', 'no_show', 'system', 'Auto-marked as no-show by cron job')
                """,
                booking_id,
            )
            return True
        except Exception as e:
            raise RuntimeError(f"mark_no_show_failed: {e}") from e
