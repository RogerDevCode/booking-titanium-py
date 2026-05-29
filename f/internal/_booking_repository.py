# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "sqlalchemy>=2.0.25",
#   "beartype>=0.19.0"
# ]
# ///
from __future__ import annotations

from uuid import UUID  # noqa: TC003

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002
from sqlalchemy.orm import selectinload

from f.internal._db_models import BookingORM


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, booking_id: UUID) -> BookingORM | None:
        """Find a booking by UUID, eager loading the client."""
        stmt = select(BookingORM).where(BookingORM.booking_id == booking_id).options(selectinload(BookingORM.client))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_active_by_client(self, client_id: UUID) -> list[BookingORM]:
        """Find all active bookings for a client."""
        stmt = select(BookingORM).where(BookingORM.client_id == client_id).where(BookingORM.status == "confirmed")
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, booking: BookingORM) -> BookingORM:
        """Save/persist a booking to the session."""
        self._session.add(booking)
        return booking
