from app.domain.protocols import DatabaseClientProtocol, TelegramSenderProtocol

from app.core.logging import logger

class NotificationService:
    """
    Handles sending reminders and system notifications.
    """
    
    def __init__(self, db: DatabaseClientProtocol, sender: TelegramSenderProtocol) -> None:
        self._db = db
        self._sender = sender
    
    async def send_reminders(self):
        """
        Sends reminders for appointments occurring in the near future.
        (Logic migrated and simplified from legacy reminder_cron)
        """
        logger.info("Cron: Checking for pending reminders...")
        # 1. Reminders for 24 hours (reminders_sent < 1)
        # 2. Reminders for 2 hours (reminders_sent < 2)
        try:
            query = """
                SELECT 
                    b.id, b.user_id, b.reminders_sent, s.start_time, p.name as provider_name,
                    COALESCE(rp.telegram_enabled, true) as telegram_enabled,
                    COALESCE(rp.email_enabled, false) as email_enabled,
                    COALESCE(rp.window_24h, true) as window_24h,
                    COALESCE(rp.window_2h, true) as window_2h
                FROM bookings b
                JOIN slots s ON b.slot_id = s.id
                JOIN providers p ON s.provider_id = p.id
                LEFT JOIN reminder_preferences rp ON b.user_id = rp.user_id
                WHERE b.status = 'CONFIRMED' 
                  AND s.start_time > NOW() 
                  AND s.start_time <= NOW() + INTERVAL '24 hours'
            """
            rows = await self._db.fetch(query)
            
            for r in rows:
                start_time = r['start_time']
                telegram_enabled = r['telegram_enabled']
                window_24h = r['window_24h']
                window_2h = r['window_2h']
                
                # Check for 2-hour reminder
                import datetime
                time_until = start_time.replace(tzinfo=datetime.timezone.utc) - datetime.datetime.now(datetime.timezone.utc)
                hours_until = time_until.total_seconds() / 3600.0
 
                from app.fsm.booking_flow import format_chile_time
 
                if hours_until <= 2.0 and r['reminders_sent'] < 2:
                    if telegram_enabled and window_2h:
                        msg = f"🔔 *Recordatorio Urgente*: Tienes una cita médica confirmada con {r['provider_name']} hoy a las {format_chile_time(start_time)}."
                        await self._sender.send_message(r['user_id'], msg)
                        logger.info("Sent 2-hour reminder", booking_id=r['id'], user_id=r['user_id'])
                    await self._db.execute("UPDATE bookings SET reminders_sent = 2 WHERE id = $1", r['id'])
                
                # Check for 24-hour reminder
                elif hours_until <= 24.0 and r['reminders_sent'] < 1:
                    if telegram_enabled and window_24h:
                        msg = f"📅 *Recordatorio*: Tienes una cita médica confirmada con {r['provider_name']} mañana a las {format_chile_time(start_time)}."
                        await self._sender.send_message(r['user_id'], msg)
                        logger.info("Sent 24-hour reminder", booking_id=r['id'], user_id=r['user_id'])
                    await self._db.execute("UPDATE bookings SET reminders_sent = 1 WHERE id = $1", r['id'])

            # Flush outbox in case the sender queues them
            if rows:
                # Get unique user ids
                user_ids = {r['user_id'] for r in rows}
                for uid in user_ids:
                    await self._sender.flush_outbox(uid)

        except Exception as e:
            logger.error("Failed to send reminders", error=str(e), exc_info=True)

    async def auto_cancel_expired_bookings(self):
        """
        Cancels 'PENDING' bookings that have exceeded the 30-minute confirmation window.
        Migrated from f/auto_cancel_expired.
        """
        try:
            # Get expired pending bookings to free their slots
            select_query = """
                SELECT id, user_id, slot_id 
                FROM bookings 
                WHERE status = 'PENDING' AND created_at < NOW() - INTERVAL '30 minutes'
            """
            rows = await self._db.fetch(select_query)
            
            if rows:
                for r in rows:
                    async with self._db.transaction():
                        await self._db.execute(
                            "UPDATE bookings SET status = 'CANCELLED', updated_at = NOW() WHERE id = $1", 
                            r['id']
                        )
                        await self._db.execute(
                            "UPDATE slots SET is_available = true WHERE id = $1", 
                            r['slot_id']
                        )
                    
                    await self._sender.send_message(
                        r['user_id'], 
                        "⚠️ Tu solicitud de reserva ha expirado por falta de confirmación."
                    )
                    
                    # Enqueue waitlist notification
                    try:
                        from app.worker.settings import WorkerSettings
                        from arq import create_pool
                        pool = await create_pool(WorkerSettings.redis_settings)
                        
                        # Get provider_id
                        slot_row = await self._db.fetchrow("SELECT provider_id FROM slots WHERE id = $1", r['slot_id'])
                        if slot_row:
                            await pool.enqueue_job("notify_waitlist", str(r['slot_id']), str(slot_row['provider_id']))
                        await pool.close()
                    except Exception as e:
                        logger.error("Failed to trigger waitlist on auto-cancel", error=str(e))
                        
                logger.info("Auto-cancelled expired bookings", count=len(rows))
        except Exception as e:
            logger.error("Auto-cancel cron failed", error=str(e))

