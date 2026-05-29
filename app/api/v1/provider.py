from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel
from datetime import datetime, date
from app.core.logging import logger
from app.fsm.booking_flow import format_confirmation_date_time

router = APIRouter()

class ExceptionCreate(BaseModel):
    start_datetime: datetime
    end_datetime: datetime
    reason: str

class SettingsUpdate(BaseModel):
    slot_duration_minutes: int
    buffer_time_minutes: int
    notice_period_hours: int

@router.get("/provider/{provider_id}/dashboard")
async def get_dashboard(provider_id: str, request: Request):
    db_client = request.app.state.container.db_client
    """Returns basic stats for the provider dashboard."""
    # 1. Appointments Today
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    
    today_count = await db_client.fetchrow(
        "SELECT COUNT(*) FROM bookings b JOIN slots s ON b.slot_id = s.id WHERE s.provider_id = $1 AND b.status = 'CONFIRMED' AND s.start_time >= $2 AND s.start_time <= $3",
        provider_id, today_start, today_end
    )
    
    # 2. Waitlist Count
    waitlist_count = await db_client.fetchrow(
        "SELECT COUNT(*) FROM waitlist WHERE provider_id = $1 AND status = 'ACTIVE'",
        provider_id
    )
    
    # 3. Next Appointment
    next_apt = await db_client.fetchrow(
        "SELECT s.start_time FROM bookings b JOIN slots s ON b.slot_id = s.id WHERE s.provider_id = $1 AND b.status = 'CONFIRMED' AND s.start_time > NOW() ORDER BY s.start_time ASC LIMIT 1",
        provider_id
    )
    
    return {
        "appointments_today": today_count['count'] if today_count else 0,
        "waitlist_active": waitlist_count['count'] if waitlist_count else 0,
        "next_appointment": next_apt['start_time'].isoformat() if next_apt else None
    }

@router.get("/provider/{provider_id}/appointments")
async def get_appointments(provider_id: str, start_date: datetime, end_date: datetime, request: Request):
    db_client = request.app.state.container.db_client
    """Returns appointments for a specific date range."""
    query = """
        SELECT b.id, s.start_time, s.end_time, u.first_name, u.last_name, b.status
        FROM bookings b
        JOIN slots s ON b.slot_id = s.id
        JOIN users u ON b.user_id = u.id
        WHERE s.provider_id = $1 AND s.start_time >= $2 AND s.start_time <= $3
        ORDER BY s.start_time ASC
    """
    rows = await db_client.fetch(query, provider_id, start_date, end_date)
    return [{
        "id": r['id'],
        "start_time": r['start_time'].isoformat(),
        "end_time": r['end_time'].isoformat(),
        "patient": f"{r['first_name']} {r.get('last_name', '')}".strip(),
        "status": r['status']
    } for r in rows]

async def cancel_and_notify_patients(provider_id: str, start_dt: datetime, end_dt: datetime, db_client, telegram_sender, slot_engine):
    # Find all confirmed bookings in this time block
    query = """
        SELECT b.id, b.user_id, s.start_time 
        FROM bookings b
        JOIN slots s ON b.slot_id = s.id
        WHERE s.provider_id = $1 AND b.status = 'CONFIRMED' 
          AND s.start_time >= $2 AND s.start_time < $3
    """
    bookings_to_cancel = await db_client.fetch(query, provider_id, start_dt, end_dt)
    
    for b in bookings_to_cancel:
        # Cancel booking
        await db_client.execute("UPDATE bookings SET status = 'CANCELLED', updated_at = NOW() WHERE id = $1", b['id'])
        # Slot is also marked as unavailable, though exception handles it anyway
        await db_client.execute("UPDATE slots SET is_available = false WHERE id = (SELECT slot_id FROM bookings WHERE id = $1)", b['id'])
        
        # Format date for user
        date_str, time_str = format_confirmation_date_time(b['start_time'].isoformat())
        
        msg = (
            "⚠️ *Aviso Importante sobre tu Cita*\n\n"
            f"Lamentamos informarte que por un imprevisto de fuerza mayor del profesional, "
            f"tu cita del *{date_str} a las {time_str}* ha sido cancelada.\n\n"
            "Para escoger una nueva hora con prioridad, ingresa al menú principal y selecciona *Reagendar hora*."
        )
        try:
            await telegram_sender.send_message(b['user_id'], msg)
        except Exception as e:
            logger.error("Failed to notify user of provider cancellation", error=str(e), user_id=b['user_id'])
            
    # Trigger slot generator to update DB immediately
    
    try:
        await slot_engine.generate_slots_for_provider(provider_id)
    except Exception as e:
        logger.error("Failed to refresh slots after exception", error=str(e))

@router.post("/provider/{provider_id}/exceptions")
async def create_exception(provider_id: str, exc: ExceptionCreate, background_tasks: BackgroundTasks, request: Request):
    db_client = request.app.state.container.db_client
    telegram_sender = request.app.state.container.telegram_sender
    slot_engine = request.app.state.container.slot_engine
    """Creates a time block/exception and cancels affected appointments."""
    await db_client.execute(
        "INSERT INTO provider_exceptions (provider_id, start_datetime, end_datetime, reason) VALUES ($1, $2, $3, $4)",
        provider_id, exc.start_datetime, exc.end_datetime, exc.reason
    )
    # Background task to cancel overlapping appointments and notify
    background_tasks.add_task(cancel_and_notify_patients, provider_id, exc.start_datetime, exc.end_datetime, db_client, telegram_sender, slot_engine)
    
    return {"status": "success", "message": "Exception created and patients notified"}

@router.put("/provider/{provider_id}/settings")
async def update_settings(provider_id: str, settings: SettingsUpdate, request: Request):
    db_client = request.app.state.container.db_client
    await db_client.execute(
        """UPDATE providers 
           SET slot_duration_minutes = $1, buffer_time_minutes = $2, notice_period_hours = $3 
           WHERE id = $4""",
        settings.slot_duration_minutes, settings.buffer_time_minutes, settings.notice_period_hours, provider_id
    )
    return {"status": "success"}
