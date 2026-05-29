from app.db.connection import db_client
from app.domain.protocols import DatabaseClientProtocol, TelegramSenderProtocol

from app.core.logging import logger
from app.telegram.sender import telegram_sender

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
        # 1. Fetch appointments starting in exactly 24h, 2h or 30m that haven't been notified
        # This is a stub for the query logic which would join bookings with slots
        pass

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

notification_service = NotificationService(db=db_client, sender=telegram_sender)
