import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.db.connection import db_client
from app.core.config import settings

settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"

CHILE_TZ = ZoneInfo("America/Santiago")

# Simple list of holidays in Chile for May, June, July 2026
HOLIDAYS_2026 = [
    datetime(2026, 5, 1).date(),
    datetime(2026, 5, 21).date(),
    datetime(2026, 6, 21).date(),
    datetime(2026, 6, 29).date(),
    datetime(2026, 7, 16).date(),
]

async def seed_slots():
    doctor_id = "956d0274-09c8-468a-a948-98d2b88fbd7f"
    
    await db_client.connect()
    
    # Delete existing slots for this doctor to start fresh
    await db_client.execute("DELETE FROM bookings WHERE slot_id IN (SELECT id FROM slots WHERE provider_id = $1)", doctor_id)
    await db_client.execute("DELETE FROM slots WHERE provider_id = $1", doctor_id)
    
    start_date = datetime(2026, 5, 28, tzinfo=CHILE_TZ)
    end_date = datetime(2026, 7, 31, tzinfo=CHILE_TZ)
    
    slots_created = 0
    
    current_date = start_date
    while current_date.date() <= end_date.date():
        # Check if it's Monday to Friday (0 = Monday, 4 = Friday)
        # Check if it's a holiday
        if current_date.weekday() < 5 and current_date.date() not in HOLIDAYS_2026:
            # Create slots from 08:00 to 15:00 (last slot starts at 15:00)
            for hour in range(8, 16): # 8, 9, 10, ..., 15
                slot_start_local = datetime(
                    current_date.year, current_date.month, current_date.day,
                    hour, 0, 0, tzinfo=CHILE_TZ
                )
                slot_end_local = slot_start_local + timedelta(hours=1)
                
                # Convert to UTC for saving in DB (though asyncpg handles timezone-aware datetimes)
                # We'll just pass the timezone-aware datetime directly to asyncpg
                
                # We skip slots that are already in the past
                if slot_start_local > datetime.now(CHILE_TZ):
                    await db_client.execute(
                        """
                        INSERT INTO slots (provider_id, start_time, end_time, is_available)
                        VALUES ($1, $2, $3, $4)
                        """,
                        doctor_id,
                        slot_start_local,
                        slot_end_local,
                        True
                    )
                    slots_created += 1
                
        current_date += timedelta(days=1)
        
    print(f"Successfully seeded {slots_created} slots for Dr. Juan Perez.")
    await db_client.disconnect()

if __name__ == "__main__":
    asyncio.run(seed_slots())
