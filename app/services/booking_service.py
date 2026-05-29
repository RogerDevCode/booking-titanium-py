from typing import List, Optional
from app.domain.entities import Specialty, Provider, AppointmentSlot, Booking, BookingView
from app.domain.protocols import BookingRepositoryProtocol

class BookingService:
    def __init__(self, repo: BookingRepositoryProtocol) -> None:
        self._repo = repo
    async def get_user_bookings(self, user_id: int) -> List[BookingView]:
        return await self._repo.get_user_bookings_view(user_id)

    async def cancel_booking(self, user_id: int, booking_id: int) -> Optional[str]:
        return await self._repo.cancel_booking_tx(user_id, booking_id)

    async def reschedule_booking(self, user_id: int, old_booking_id: int, new_slot_id: str) -> tuple[Booking, str]:
        return await self._repo.reschedule_booking_tx(user_id, old_booking_id, new_slot_id)

    async def get_all_specialties(self) -> List[Specialty]:
        return await self._repo.get_all_specialties()

    async def get_providers_by_specialty(self, specialty_id: str) -> List[Provider]:
        return await self._repo.get_providers_by_specialty(specialty_id)

    async def get_available_slots(self, provider_id: str, limit: int = 15) -> List[AppointmentSlot]:
        return await self._repo.get_available_slots(provider_id, limit=limit)

    async def create_booking(self, user_id: int, slot_id: str) -> Booking:
        return await self._repo.create_booking_tx(user_id, slot_id)

    async def add_to_waitlist(self, user_id: int, provider_id: str) -> None:
        await self._repo.add_to_waitlist(user_id, provider_id)

    async def get_provider_id_by_slot(self, slot_id: str) -> Optional[str]:
        return await self._repo.get_provider_id_by_slot(slot_id)

