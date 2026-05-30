from typing import List, Optional
from app.domain.entities import Booking, BookingView, Specialty, Provider, AppointmentSlot
from app.domain.enums import BookingStatus
from app.domain.protocols import DatabaseClientProtocol

from app.core.logging import logger

class BookingRepository:
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db
    async def get_user_bookings_view(self, user_id: int) -> List[BookingView]:
        query = """
            SELECT 
                b.id, b.status, s.start_time, 
                p.name as provider_name, sp.name as specialty_name
            FROM bookings b
            JOIN slots s ON b.slot_id = s.id
            JOIN providers p ON s.provider_id = p.id
            JOIN specialties sp ON p.specialty_id = sp.id
            WHERE b.user_id = $1 AND b.status = 'CONFIRMED' AND s.start_time > NOW()
            ORDER BY s.start_time ASC
        """
        rows = await self._db.fetch(query, user_id)
        return [
            BookingView(
                id=r['id'],
                status=BookingStatus(r['status']),
                start_time=r['start_time'],
                provider_name=r['provider_name'],
                specialty_name=r['specialty_name']
            ) for r in rows
        ]

    async def cancel_booking_tx(self, user_id: int, booking_id: int) -> Optional[str]:
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                query_lock = "SELECT slot_id FROM bookings WHERE id = $1 AND user_id = $2 AND status = 'CONFIRMED' FOR UPDATE"
                row = await conn.fetchrow(query_lock, booking_id, user_id)
                if not row:
                    logger.warning("Cancellation failed: booking not found or unauthorized", booking_id=booking_id, user_id=user_id)
                    return None
                
                slot_id = row['slot_id']
                await conn.execute("UPDATE bookings SET status = 'CANCELLED', updated_at = NOW() WHERE id = $1", booking_id)
                await conn.execute("UPDATE slots SET is_available = true WHERE id = $1", slot_id)
                return str(slot_id)

    async def reschedule_booking_tx(self, user_id: int, old_booking_id: int, new_slot_id: str) -> tuple[Booking, str]:
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                query_old = "SELECT slot_id FROM bookings WHERE id = $1 AND user_id = $2 AND status = 'CONFIRMED' FOR UPDATE"
                old_row = await conn.fetchrow(query_old, old_booking_id, user_id)
                if not old_row:
                    raise ValueError("Original booking not found or ineligible for rescheduling")
                
                old_slot_id = old_row['slot_id']

                query_new = "SELECT id FROM slots WHERE id = $1 AND is_available = true FOR UPDATE"
                new_row = await conn.fetchrow(query_new, int(new_slot_id))
                if not new_row:
                    raise ValueError("New slot no longer available")

                await conn.execute("UPDATE bookings SET status = 'CANCELLED', updated_at = NOW() WHERE id = $1", old_booking_id)
                await conn.execute("UPDATE slots SET is_available = true WHERE id = $1", old_slot_id)
                await conn.execute("UPDATE slots SET is_available = false WHERE id = $1", int(new_slot_id))

                query_insert = """
                    INSERT INTO bookings (user_id, slot_id, status)
                    VALUES ($1, $2, $3)
                    RETURNING id, user_id, slot_id, status, created_at, updated_at
                """
                row = await conn.fetchrow(query_insert, user_id, int(new_slot_id), BookingStatus.CONFIRMED.value)
                
                booking = Booking(
                    id=row['id'],
                    user_id=row['user_id'],
                    slot_id=str(row['slot_id']),
                    status=BookingStatus(row['status']),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )
                return booking, str(old_slot_id)

    async def get_all_specialties(self) -> List[Specialty]:
        query = "SELECT id::text AS id, name, description FROM specialties ORDER BY name ASC"
        try:
            rows = await self._db.fetch(query)
            return [Specialty(id=r['id'], name=r['name'], description=r['description']) for r in rows]
        except Exception as e:
            logger.error("Failed to fetch specialties", error=str(e), query=query)
            raise

    async def get_providers_by_specialty(self, specialty_id: str) -> List[Provider]:
        query = """
            SELECT 
                id::text AS id, name, specialty_id::text AS specialty_id, bio, is_active,
                waitlist_batch_size, waitlist_delay_minutes, slot_duration_minutes, 
                buffer_time_minutes, notice_period_hours,
                gcal_calendar_id, gcal_access_token, gcal_refresh_token,
                gcal_client_id, gcal_client_secret
            FROM providers 
            WHERE specialty_id = $1 AND is_active = true 
            ORDER BY name ASC
        """
        rows = await self._db.fetch(query, int(specialty_id))
        return [
            Provider(
                id=r['id'], 
                name=r['name'], 
                specialty_id=r['specialty_id'], 
                bio=r['bio'], 
                is_active=r['is_active'],
                waitlist_batch_size=r.get('waitlist_batch_size', 3),
                waitlist_delay_minutes=r.get('waitlist_delay_minutes', 15),
                slot_duration_minutes=r.get('slot_duration_minutes', 30),
                buffer_time_minutes=r.get('buffer_time_minutes', 0),
                notice_period_hours=r.get('notice_period_hours', 4),
                gcal_calendar_id=r.get('gcal_calendar_id'),
                gcal_access_token=r.get('gcal_access_token'),
                gcal_refresh_token=r.get('gcal_refresh_token'),
                gcal_client_id=r.get('gcal_client_id'),
                gcal_client_secret=r.get('gcal_client_secret')
            ) for r in rows
        ]

    async def get_available_slots(self, provider_id: str, limit: int = 15) -> List[AppointmentSlot]:
        query = """
            SELECT id::text AS id, provider_id::text as doctor_id, start_time, end_time, is_available 
            FROM slots 
            WHERE provider_id = $1 AND is_available = true AND start_time > NOW()
            ORDER BY start_time ASC LIMIT $2
        """
        rows = await self._db.fetch(query, int(provider_id), limit)
        return [AppointmentSlot(id=r['id'], doctor_id=r['doctor_id'], start_time=r['start_time'], end_time=r['end_time'], is_available=r['is_available']) for r in rows]

    async def create_booking_tx(self, user_id: int, slot_id: str) -> Booking:
        async with self._db.pool.acquire() as conn:
            async with conn.transaction():
                query_slot = "SELECT id FROM slots WHERE id = $1 AND is_available = true FOR UPDATE"
                slot = await conn.fetchrow(query_slot, int(slot_id))
                if not slot:
                    raise ValueError("Slot no longer available")

                await conn.execute("UPDATE slots SET is_available = false WHERE id = $1", int(slot_id))

                query_booking = """
                    INSERT INTO bookings (user_id, slot_id, status)
                    VALUES ($1, $2, $3)
                    RETURNING id, user_id, slot_id, status, created_at, updated_at
                """
                row = await conn.fetchrow(query_booking, user_id, int(slot_id), BookingStatus.CONFIRMED.value)
                
                return Booking(
                    id=row['id'],
                    user_id=row['user_id'],
                    slot_id=str(row['slot_id']),
                    status=BookingStatus(row['status']),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                )

    async def get_provider_id_by_booking(self, booking_id: int) -> str:
        query = "SELECT s.provider_id::text FROM bookings b JOIN slots s ON b.slot_id = s.id WHERE b.id = $1"
        row = await self._db.fetchrow(query, booking_id)
        return str(row["provider_id"]) if row else ""

    async def add_to_waitlist(self, user_id: int, provider_id: str) -> None:
        query = """
            INSERT INTO waitlist (user_id, provider_id)
            VALUES ($1, $2)
            ON CONFLICT (user_id, provider_id, status) DO NOTHING
        """
        await self._db.execute(query, user_id, int(provider_id))

    async def get_provider_id_by_slot(self, slot_id: str) -> Optional[str]:
        query = "SELECT provider_id::text FROM slots WHERE id = $1"
        row = await self._db.fetchrow(query, int(slot_id))
        return row['provider_id'] if row else None

    async def get_history_by_month(self, user_id: int, year: int, month: int) -> List[BookingView]:
        query = """
            SELECT 
                b.id, b.status, s.start_time, 
                p.name as provider_name, sp.name as specialty_name
            FROM bookings b
            JOIN slots s ON b.slot_id = s.id
            JOIN providers p ON s.provider_id = p.id
            JOIN specialties sp ON p.specialty_id = sp.id
            WHERE b.user_id = $1 
              AND EXTRACT(YEAR FROM s.start_time) = $2 
              AND EXTRACT(MONTH FROM s.start_time) = $3
            ORDER BY s.start_time DESC
        """
        rows = await self._db.fetch(query, user_id, year, month)
        return [
            BookingView(
                id=r['id'],
                status=BookingStatus(r['status']),
                start_time=r['start_time'],
                provider_name=r['provider_name'],
                specialty_name=r['specialty_name']
            ) for r in rows
        ]

    async def get_history_all(self, user_id: int) -> List[BookingView]:
        query = """
            SELECT 
                b.id, b.status, s.start_time, 
                p.name as provider_name, sp.name as specialty_name
            FROM bookings b
            JOIN slots s ON b.slot_id = s.id
            JOIN providers p ON s.provider_id = p.id
            JOIN specialties sp ON p.specialty_id = sp.id
            WHERE b.user_id = $1 
              AND s.start_time >= NOW() - INTERVAL '24 months'
            ORDER BY s.start_time DESC
        """
        rows = await self._db.fetch(query, user_id)
        return [
            BookingView(
                id=r['id'],
                status=BookingStatus(r['status']),
                start_time=r['start_time'],
                provider_name=r['provider_name'],
                specialty_name=r['specialty_name']
            ) for r in rows
        ]

