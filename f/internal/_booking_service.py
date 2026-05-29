# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "sqlalchemy>=2.0.25"
# ]
# ///
from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from f.internal._booking_repository import BookingRepository
from f.internal._db_models import BookingORM
from f.internal._db_sqlalchemy import async_session_factory


class BookingService:
    async def create_booking(
        self,
        client_id: UUID,
        provider_id: UUID,
        service_id: UUID,
        start_time: datetime,
        end_time: datetime,
        idempotency_key: str,
    ) -> BookingORM:
        """Create a new booking within a managed transaction context."""
        async with async_session_factory() as session, session.begin():
            repo = BookingRepository(session)
            booking = BookingORM(
                client_id=client_id,
                provider_id=provider_id,
                service_id=service_id,
                start_time=start_time,
                end_time=end_time,
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            await repo.save(booking)
            return booking
