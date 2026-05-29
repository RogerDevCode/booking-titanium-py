from datetime import datetime, timedelta, time
from typing import List, Dict, Any
import pytz
from zoneinfo import ZoneInfo
from app.db.connection import db_client
from app.domain.protocols import DatabaseClientProtocol

from app.core.logging import logger

CHILE_TZ = ZoneInfo("America/Santiago")

class SlotEngine:
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db
    async def generate_slots_for_all_providers(self, days: int = 60):
        """Generates slots for all active providers."""
        providers = await self._db.fetch("SELECT id FROM providers WHERE is_active = true")
        for p in providers:
            try:
                await self.generate_slots_for_provider(str(p['id']), days)
            except Exception as e:
                logger.error("Failed generating slots for provider", provider_id=str(p['id']), error=str(e))

    async def generate_slots_for_provider(self, provider_id: str, days: int = 60):
        logger.info("Generating slots for provider", provider_id=provider_id, days=days)
        
        # 1. Fetch provider settings
        provider = await self._db.fetchrow(
            "SELECT slot_duration_minutes, buffer_time_minutes, notice_period_hours FROM providers WHERE id = $1", 
            provider_id
        )
        if not provider:
            return
            
        slot_duration = timedelta(minutes=provider['slot_duration_minutes'])
        buffer_time = timedelta(minutes=provider['buffer_time_minutes'])
        
        # 2. Fetch schedules
        schedules = await self._db.fetch(
            "SELECT day_of_week, start_time, end_time FROM provider_schedules WHERE provider_id = $1 AND is_active = true",
            provider_id
        )
        if not schedules:
            return # No schedule defined
            
        # Group schedules by day of week (0=Monday, 6=Sunday)
        schedules_by_day = {i: [] for i in range(7)}
        for s in schedules:
            schedules_by_day[s['day_of_week']].append(s)

        # 3. Fetch exceptions
        now_local = datetime.now(CHILE_TZ)
        end_date_local = now_local + timedelta(days=days)
        
        exceptions = await self._db.fetch(
            "SELECT start_datetime, end_datetime FROM provider_exceptions WHERE provider_id = $1 AND end_datetime >= $2 AND start_datetime <= $3",
            provider_id, now_local, end_date_local
        )

        generated_slots = []
        
        # Iterate over each day
        current_date = now_local.date()
        for i in range(days + 1):
            target_date = current_date + timedelta(days=i)
            day_of_week = target_date.weekday()
            
            day_schedules = schedules_by_day[day_of_week]
            for schedule in day_schedules:
                # Construct aware datetimes for the start and end of this schedule block
                # schedule['start_time'] is a datetime.time object
                block_start = datetime.combine(target_date, schedule['start_time']).replace(tzinfo=CHILE_TZ)
                block_end = datetime.combine(target_date, schedule['end_time']).replace(tzinfo=CHILE_TZ)
                
                # If block_start is in the past (e.g. today's past hours), adjust it? No, just let it generate, 
                # but maybe only keep slots > now + notice_period.
                
                current_slot_start = block_start
                while current_slot_start + slot_duration <= block_end:
                    current_slot_end = current_slot_start + slot_duration
                    
                    # Check exceptions overlap
                    overlap = False
                    for ex in exceptions:
                        # Ex are aware datetimes
                        if current_slot_start < ex['end_datetime'] and current_slot_end > ex['start_datetime']:
                            overlap = True
                            break
                            
                    if not overlap:
                        # Only keep slots in the future + notice period
                        min_start_time = now_local + timedelta(hours=provider['notice_period_hours'])
                        if current_slot_start >= min_start_time:
                            generated_slots.append({
                                'start_time': current_slot_start,
                                'end_time': current_slot_end
                            })
                            
                    current_slot_start = current_slot_end + buffer_time

        # 4. Sync with DB
        # We'll use a transaction to safely insert the generated slots
        # For simplicity, we insert slots that don't exist.
        inserted_count = 0
        async with self._db.transaction():
            for slot in generated_slots:
                res = await self._db.execute(
                    """
                    INSERT INTO slots (provider_id, start_time, end_time, is_available)
                    VALUES ($1, $2, $3, true)
                    ON CONFLICT (provider_id, start_time) DO NOTHING
                    """,
                    provider_id, slot['start_time'], slot['end_time']
                )
                if res == "INSERT 0 1":
                    inserted_count += 1
                    
        logger.info("Generated new slots", provider_id=provider_id, new_slots=inserted_count)

slot_engine = SlotEngine(db=db_client)
