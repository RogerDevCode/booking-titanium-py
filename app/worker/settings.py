from arq import cron
from arq.connections import RedisSettings
from app.container import Container

from app.worker.tasks import (
    make_process_message,
    make_cron_auto_cancel,
    make_cron_noshow_trigger,
    make_cron_reminders,
    make_cron_flush_outbox,
    make_notify_waitlist,
    make_cron_generate_slots,
    make_sync_booking_to_gcal,
    make_delete_gcal_event,
    make_cron_reconcile_gcal
)

def create_worker_settings(container: Container) -> type:
    fn_process_message = make_process_message(container)
    fn_cron_auto_cancel = make_cron_auto_cancel(container)
    fn_cron_noshow_trigger = make_cron_noshow_trigger(container)
    fn_cron_reminders = make_cron_reminders(container)
    fn_cron_flush_outbox = make_cron_flush_outbox(container)
    fn_notify_waitlist = make_notify_waitlist(container)
    fn_cron_generate_slots = make_cron_generate_slots(container)
    fn_sync_booking_to_gcal = make_sync_booking_to_gcal(container)
    fn_delete_gcal_event = make_delete_gcal_event(container)
    fn_cron_reconcile_gcal = make_cron_reconcile_gcal(container)

    class WorkerSettings:
        """Configuration for ARQ worker."""
        functions = [
            fn_process_message,
            fn_cron_auto_cancel,
            fn_cron_noshow_trigger,
            fn_cron_reminders,
            fn_cron_flush_outbox,
            fn_notify_waitlist,
            fn_cron_generate_slots,
            fn_sync_booking_to_gcal,
            fn_delete_gcal_event,
            fn_cron_reconcile_gcal
        ]
        cron_jobs = [
            # Every 10 minutes (0, 10, 20...)
            cron(fn_cron_auto_cancel, minute={0, 10, 20, 30, 40, 50}, second=0),
            # Every 10 minutes, offset by 2 (2, 12, 22...) for no-show checks
            cron(fn_cron_noshow_trigger, minute={2, 12, 22, 32, 42, 52}, second=0),
            # Every 10 minutes, offset by 5 (5, 15, 25...) to distribute load
            cron(fn_cron_reminders, minute={5, 15, 25, 35, 45, 55}, second=0),
            # Fallback outbox flush every 1 minute
            cron(fn_cron_flush_outbox, minute=set(range(60)), second=0),
            # Slot generator every day at 02:00
            cron(fn_cron_generate_slots, hour=2, minute=0, second=0),
            # Google Calendar reconciliation every 5 minutes
            cron(fn_cron_reconcile_gcal, minute=set(range(0, 60, 5)), second=0),
        ]
        redis_settings = RedisSettings.from_dsn(container.settings.REDIS_URL)
        max_jobs = 10
        job_timeout = container.settings.WORKER_TIMEOUT

        @staticmethod
        async def on_startup(ctx: dict) -> None:
            await container.redis_client.connect()
            await container.db_client.connect()

        @staticmethod
        async def on_shutdown(ctx: dict) -> None:
            await container.db_client.disconnect()
            await container.redis_client.disconnect()

    return WorkerSettings

# Temporary backward compatibility fallback for tools that might import WorkerSettings directly
from app.core.config import settings  # noqa: E402
try:
    from app.container import build_container
    _temp_container = build_container(settings)
    WorkerSettings = create_worker_settings(_temp_container)
except Exception:
    pass
