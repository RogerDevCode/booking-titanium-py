from fastapi import APIRouter, Depends, Request
from datetime import datetime, date
from app.middleware.auth import get_current_user

router = APIRouter()

@router.get("/dashboard/stats")
async def get_dashboard_stats(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    role = current_user["role"]
    provider_id = current_user.get("provider_id")
    
    async with db.transaction() as conn:
        if role == "provider" and provider_id:
            # Set RLS context for the provider
            await conn.execute("SELECT set_config('app.current_provider_id', $1, true)", str(provider_id))
            await conn.execute("SELECT set_config('app.admin_override', 'false', true)")
        else:
            # Set RLS context for admin (bypass RLS)
            await conn.execute("SELECT set_config('app.current_provider_id', '0', true)")
            await conn.execute("SELECT set_config('app.admin_override', 'true', true)")
        
        # 1. Appointments Today
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end = datetime.combine(date.today(), datetime.max.time())
        
        today_count = await conn.fetchrow(
            """SELECT COUNT(*) FROM bookings b 
               JOIN slots s ON b.slot_id = s.id 
               WHERE b.status = 'CONFIRMED' AND s.start_time >= $1 AND s.start_time <= $2""",
            today_start, today_end
        )
        
        # 2. Waitlist Count
        waitlist_count = await conn.fetchrow(
            "SELECT COUNT(*) FROM waitlist WHERE status = 'ACTIVE'"
        )
        
        # 3. Next Appointment
        next_apt = await conn.fetchrow(
            """SELECT s.start_time, u.first_name, u.last_name FROM bookings b 
               JOIN slots s ON b.slot_id = s.id 
               JOIN users u ON b.user_id = u.id
               WHERE b.status = 'CONFIRMED' AND s.start_time > NOW() 
               ORDER BY s.start_time ASC LIMIT 1"""
        )
        
        # 4. Total Active Providers
        providers_count = await conn.fetchrow(
            "SELECT COUNT(*) FROM providers WHERE is_active = true"
        )
        
        # 5. Recent Appointments (Recent 5)
        recent_apts = await conn.fetch(
            """SELECT b.id, s.start_time, s.end_time, u.first_name, u.last_name, b.status 
               FROM bookings b 
               JOIN slots s ON b.slot_id = s.id 
               JOIN users u ON b.user_id = u.id
               ORDER BY s.start_time DESC LIMIT 5"""
        )
        
        return {
            "appointments_today": today_count['count'] if today_count else 0,
            "waitlist_active": waitlist_count['count'] if waitlist_count else 0,
            "next_appointment": {
                "start_time": next_apt['start_time'].isoformat() if next_apt else None,
                "patient": f"{next_apt['first_name']} {next_apt.get('last_name', '')}".strip() if next_apt else None
            },
            "active_providers": providers_count['count'] if providers_count else 0,
            "recent_appointments": [{
                "id": r['id'],
                "start_time": r['start_time'].isoformat(),
                "end_time": r['end_time'].isoformat(),
                "patient": f"{r['first_name']} {r.get('last_name', '')}".strip(),
                "status": r['status']
            } for r in recent_apts]
        }
