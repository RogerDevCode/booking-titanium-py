from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import traceback
from typing import Any, ClassVar, Final, cast

from arq import Retry, cron
from arq.connections import RedisSettings

from ..auto_cancel_expired.main import _main_async as run_auto_cancel_expired
from ..gcal_reconcile.main import _main_async as run_gcal_reconcile
from ..internal._db_client import create_db_client
from ..internal._redis_client import create_redis_client
from ..internal.ai_agent.main import _main_async as run_ai_agent
from ..internal.booking_confirm.main import _main_async as run_booking_confirm
from ..internal.booking_fsm import get_main_menu_inline_buttons
from ..internal.booking_prefetch.main import _main_async as run_booking_prefetch
from ..internal.client_register.main import _main_async as run_client_register
from ..internal.conversation_get.main import _get_conversation
from ..internal.conversation_update.main import _main_async as run_conversation_update
from ..internal.conversational_router.main import _main_async as run_conversational_router
from ..internal.fsm_router.main import _main_async as run_fsm_router
from ..message_preprocessor.main import _preprocess
from ..telegram_auto_register.main import _main_async as run_telegram_auto_register
from ..telegram_callback.main import _main_async as run_telegram_callback
from ..telegram_send.main import _main_async as run_telegram_send
from ._gateway_models import TelegramUpdate
from .monitoring import MetricsTracker, log_structured

MODULE: Final[str] = "telegram_worker"

# Load essential vars
TELEGRAM_BOT_TOKEN: Final[str] = os.getenv("TELEGRAM_BOT_TOKEN", "")
DATABASE_URL: Final[str] = os.getenv("DATABASE_URL", "")
REDIS_URL: Final[str] = os.getenv("REDIS_URL", "redis://redis:6379")
_BACKGROUND_TASKS: Final[set[asyncio.Task[Any]]] = set()


async def startup(ctx: dict[str, Any]) -> None:
    """Initialize DB and Redis pools at worker startup."""
    log_structured(logging.INFO, "worker_startup_initiated")

    # Warm up pools globally
    db_conn = await create_db_client(DATABASE_URL)
    await db_conn.close()  # Re-releases connection to global pool

    redis = await create_redis_client(REDIS_URL)
    ctx["redis"] = redis
    ctx["metrics"] = MetricsTracker(redis)

    log_structured(logging.INFO, "worker_startup_completed")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Clean up pool resources at worker shutdown."""
    log_structured(logging.INFO, "worker_shutdown_initiated")
    if "redis" in ctx:
        await ctx["redis"].aclose()
    log_structured(logging.INFO, "worker_shutdown_completed")


async def process_telegram_update(ctx: dict[str, Any], update_json: str, ingest_timestamp: float | None = None) -> None:
    """Orchestrate the entire Telegram update processing pipeline in-process."""
    start_time = time.perf_counter()
    metrics: MetricsTracker = ctx["metrics"]
    redis = ctx["redis"]
    await metrics.increment_requests()

    if ingest_timestamp is not None:
        queue_delay_ms = (time.time() - ingest_timestamp) * 1000
        await metrics.record_queuing_delay(queue_delay_ms)

    # 1. Parse and validate boundary
    try:
        update = TelegramUpdate.model_validate_json(update_json)
    except Exception as e:
        await metrics.increment_errors()
        log_structured(logging.ERROR, "update_parse_failed", error=str(e))
        raise RuntimeError(f"worker parse error: {e}") from e

    chat_id: str | None = None
    text: str = ""
    first_name: str = "Usuario"
    last_name: str | None = None
    username: str = "unknown"
    callback_data: str | None = None
    callback_query_id: str | None = None
    callback_message_id: int | None = None

    if update.message:
        chat_id = str(update.message.chat.id)
        text = update.message.text or ""
        if update.message.from_user:
            first_name = update.message.from_user.first_name
            last_name = update.message.from_user.last_name
            username = update.message.from_user.username or "unknown"
    elif update.callback_query:
        if update.callback_query.message:
            chat_id = str(update.callback_query.message.chat.id)
            callback_message_id = update.callback_query.message.message_id
        callback_data = update.callback_query.data
        callback_query_id = update.callback_query.id
        first_name = update.callback_query.from_user.first_name if update.callback_query.from_user else "Usuario"
        last_name = update.callback_query.from_user.last_name if update.callback_query.from_user else None
        username = (update.callback_query.from_user.username if update.callback_query.from_user else None) or "unknown"

    if not chat_id:
        log_structured(logging.WARNING, "skipped_update_no_chat_id", update_id=update.update_id)
        return

    # 2. Acquire user-level FSM lock in Redis to prevent concurrent modification
    lock_key = f"lock:user:{chat_id}"
    # Acquired for max 10 seconds to avoid deadlocks
    acquired = await redis.set(lock_key, "1", nx=True, ex=10)
    if not acquired:
        log_structured(
            logging.INFO,
            "worker_lock_failed_deferring_job",
            chat_id=chat_id,
            update_id=update.update_id,
        )
        # Defer job processing for 0.3 seconds, aligning with the new low-latency FSM execution time
        raise Retry(defer=0.3)

    try:
        log_structured(logging.INFO, "update_intake_received", chat_id=chat_id, update_id=update.update_id)

        # 3. Run message preprocessor (in-memory)
        cleaned_text = text
        security_scan_failed = False
        if update.message and text:
            prep_res = _preprocess(text)
            cleaned_text = prep_res.cleaned_text
            if prep_res.security_scan and prep_res.security_scan.threat_detected:
                security_scan_failed = True
                log_structured(logging.WARNING, "security_threat_detected", chat_id=chat_id, text=text)

        # 4. Get conversation state
        conv_res = await _get_conversation(chat_id, redis_url=REDIS_URL, pg_url=DATABASE_URL)
        conv_state = conv_res.data

        # Enforce linear flow / button locking:
        # Clear inline keyboard markup of the last sent bot message (message_id) so the user cannot click old buttons.
        if conv_state and conv_state.message_id:
            import httpx as _httpx

            async def _clear_previous_markup(msg_id: int) -> None:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup"
                try:
                    async with _httpx.AsyncClient(timeout=3.0) as _client:
                        await _client.post(
                            url,
                            json={
                                "chat_id": chat_id,
                                "message_id": msg_id,
                                "reply_markup": {"inline_keyboard": []},
                            },
                        )
                except Exception as e:
                    log_structured(logging.WARNING, "clear_previous_markup_failed", chat_id=chat_id, error=str(e))
                    raise RuntimeError(f"Clear previous markup failed: {e}") from e

            _clear_prev_task = asyncio.create_task(_clear_previous_markup(conv_state.message_id))
            _BACKGROUND_TASKS.add(_clear_prev_task)
            _clear_prev_task.add_done_callback(_BACKGROUND_TASKS.discard)

        # 5. Register client (if not already exists)
        reg_args: dict[str, object] = {
            "chat_id": chat_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
        }
        reg_res = await run_telegram_auto_register(reg_args, DATABASE_URL)
        client_id = reg_res.get("client_id")
        phone = reg_res.get("phone")
        client_name = reg_res.get("name")

        # Intercept and process callback queries via telegram_callback
        if callback_data:
            parts = callback_data.split("|")[0].split(":")
            prefix = parts[0] if parts else ""
            if prefix in {"cnf", "cxl", "cxr", "res", "ars", "act", "dea", "ack"}:
                callback_args: dict[str, object] = {
                    "callback_query_id": callback_query_id,
                    "callback_data": callback_data,
                    "chat_id": chat_id,
                    "client_id": str(client_id) if client_id else None,
                    "user_id": str(client_id) if client_id else None,
                }
                await run_telegram_callback(callback_args)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                await metrics.record_processing_time(elapsed_ms)
                log_structured(
                    logging.INFO,
                    "update_processing_completed",
                    chat_id=chat_id,
                    update_id=update.update_id,
                    elapsed_ms=elapsed_ms,
                )
                return

        # 6. Route to AI Agent for intent classification
        intent = "desconocido"
        requires_fsm_routing = True
        ai_resp: str | None = None
        ai_entities: dict[str, Any] = {}
        ai_confidence = 0.0

        if not security_scan_failed and cleaned_text and cleaned_text != "/start":
            state_name = conv_state.booking_state.get("name") if conv_state and conv_state.booking_state else "idle"
            state_dict = {
                "active_flow": conv_state.active_flow if conv_state else "none",
                "flow_step": conv_state.flow_step if conv_state else 0,
                "pending_data": conv_state.pending_data if conv_state else {},
                "booking_state_name": state_name,
            }
            ai_agent_args = {
                "chat_id": chat_id,
                "text": cleaned_text,
                "conversation_state": state_dict,
                "pg_url": DATABASE_URL,
                "groq_api_key": os.getenv("GROQ_API_KEY", ""),
                "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
            }
            ai_agent_res = await run_ai_agent(ai_agent_args)
            if ai_agent_res.get("success") and ai_agent_res.get("data"):
                ai_data = cast("dict[str, Any]", ai_agent_res["data"])
                intent = ai_data.get("intent", "desconocido")
                requires_fsm_routing = ai_data.get("requires_fsm_routing", True)
                ai_resp = ai_data.get("ai_response")
                ai_entities = ai_data.get("entities", {})
                ai_confidence = ai_data.get("confidence", 0.0)

        # Handle commands directly
        if cleaned_text == "/start":
            intent = "menu_principal"
            requires_fsm_routing = True

        # 7. FSM Prefetch & Route (if applicable)
        fsm_handled = False
        fsm_outcome: dict[str, Any] = {}
        if requires_fsm_routing and not security_scan_failed:
            prefetch_res = await run_booking_prefetch(
                booking_state=conv_state.booking_state if conv_state else None,
                booking_draft=conv_state.booking_draft if conv_state else None,
                pg_url=DATABASE_URL,
                user_input=cleaned_text or callback_data,
                client_id=str(client_id) if client_id else None,
            )
            items = prefetch_res.get("items", [])
            prefetch_block_reason = prefetch_res.get("block_reason")

            fsm_args: dict[str, object] = {
                "chat_id": chat_id,
                "user_input": cleaned_text or callback_data,
                "state": conv_state.model_dump() if conv_state else {},
                "items": items,
                "phone": phone,
                "client_name": client_name,
                "prefetch_block_reason": prefetch_block_reason,
                "client_id": client_id,
                "callback_message_id": callback_message_id,
                "update_id": update.update_id,
                "pg_url": DATABASE_URL,
                "ai_intent": intent,
                "ai_confidence": ai_confidence,
                "ai_entities": ai_entities,
                "requires_fsm_routing": requires_fsm_routing,
            }
            fsm_res_raw = await run_fsm_router(fsm_args)
            fsm_outcome = cast("dict[str, Any]", fsm_res_raw.get("data", {}))
            fsm_handled = bool(fsm_outcome.get("handled", False))

        # 8. Conversational Route (if FSM didn't handle it)
        conv_outcome: dict[str, Any] = {}
        if not fsm_handled and not security_scan_failed:
            curr_state = conv_state.booking_state.get("name") if conv_state and conv_state.booking_state else "idle"
            sess_id = conv_state.booking_state.get("session_id") if conv_state and conv_state.booking_state else None
            conv_args: dict[str, object] = {
                "chat_id": chat_id,
                "user_input": cleaned_text or callback_data,
                "ai_intent": intent,
                "ai_confidence": ai_confidence,
                "ai_response": ai_resp,
                "client_id": client_id,
                "client_name": client_name,
                "phone": phone,
                "pg_url": DATABASE_URL,
                "current_state_name": curr_state,
                "session_id": sess_id,
            }
            conv_res_raw = await run_conversational_router(conv_args)
            conv_outcome = cast("dict[str, Any]", conv_res_raw.get("data", {}))

        # 9. Register client metadata if FSM router requested it
        if fsm_outcome.get("registration_data"):
            meta = fsm_outcome["registration_data"]
            await run_client_register(
                client_id=str(client_id),
                name=meta.get("name"),
                email=meta.get("email"),
                phone=meta.get("phone"),
                pg_url=DATABASE_URL,
            )

        # 10. Booking Commit (if transitioning from confirming -> idle)
        booking_commit_outcome: dict[str, Any] = {}
        if (
            conv_state
            and conv_state.booking_state
            and conv_state.booking_state.get("name") == "confirming"
            and fsm_outcome.get("nextState", {}).get("name") == "idle"
            and not security_scan_failed
        ):
            booking_commit_outcome = await run_booking_confirm(
                client_id=str(client_id),
                provider_id=str(conv_state.booking_state.get("doctorId")),
                start_time=str(conv_state.booking_state.get("draft", {}).get("start_time")),
                chat_id=chat_id,
                pg_url=DATABASE_URL,
                redis_url=REDIS_URL,
                version=conv_state.version,
            )

        # 11. Persist State Update (skip if booking_confirm already updated database and version)
        if not booking_commit_outcome.get("success"):
            next_state = fsm_outcome.get("nextState") or conv_outcome.get("nextState")
            next_draft = fsm_outcome.get("nextDraft")
            active_flow = fsm_outcome.get("active_flow")

            update_args: dict[str, object] = {
                "chat_id": chat_id,
                "booking_state": next_state,
                "active_flow": active_flow,
                "booking_draft": next_draft,
                "version": conv_state.version if conv_state else 0,
                "pending_data": {
                    "router_handled": fsm_handled or conv_outcome.get("handled", False),
                    "user_id": reg_res.get("user_id"),
                    "client_id": client_id,
                },
                "pg_url": DATABASE_URL,
            }
            await run_conversation_update(update_args)

        # 12. Format Response & Send to Telegram
        inline_buttons = fsm_outcome.get("inline_buttons") or conv_outcome.get("inline_buttons")
        edit_message = fsm_outcome.get("edit_message", False)

        # Resolve response text
        if security_scan_failed:
            response_text = "🚫 Lo siento, tu mensaje ha sido bloqueado por políticas de seguridad."
        elif booking_commit_outcome.get("success"):
            response_text = (
                f"✅ *Reserva Confirmada*\n\n"
                f"📋 {booking_commit_outcome.get('service_name')} con {booking_commit_outcome.get('provider_name')}\n"
                f"🆔 Ref: `{booking_commit_outcome.get('booking_short_id')}`\n\n"
                f"Recibirás un recordatorio antes de tu hora.\n\n📱 *Menú Principal*"
            )
            inline_buttons = get_main_menu_inline_buttons()
            edit_message = False
        elif booking_commit_outcome.get("error"):
            response_text = (
                f"❌ No se pudo confirmar la cita.\n\n"
                f"{booking_commit_outcome.get('user_message', 'Por favor intenta de nuevo en unos minutos.')}"
            )
        elif fsm_handled and fsm_outcome.get("response_text"):
            response_text = str(fsm_outcome["response_text"])
        elif conv_outcome.get("handled") and conv_outcome.get("response_text"):
            response_text = str(conv_outcome["response_text"])
        else:
            response_text = "Lo siento, no entendí tu mensaje. 😊\n\nEscribe /start para ver el menú principal."

        # Record internal processing time (everything done up to outbound API calls)
        internal_processing_ms = (time.perf_counter() - start_time) * 1000
        await metrics.record_internal_processing_time(internal_processing_ms)

        tg_outbound_start = time.perf_counter()

        # Dismiss spinner for callback queries
        if callback_query_id:
            import httpx

            async def _dismiss_spinner() -> None:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(url, json={"callback_query_id": callback_query_id}, timeout=2.0)
                except Exception:
                    pass  # Non-fatal

            # Fire-and-forget (do not await)
            _dismiss_task = asyncio.create_task(_dismiss_spinner())
            _BACKGROUND_TASKS.add(_dismiss_task)
            _dismiss_task.add_done_callback(_BACKGROUND_TASKS.discard)

        # Call send_telegram_response
        send_args: dict[str, object] = {
            "bot_token": TELEGRAM_BOT_TOKEN,
            "chat_id": chat_id,
            "inline_buttons": inline_buttons if inline_buttons else [],
            "message_id": callback_message_id if edit_message else None,
            "mode": "edit_message" if edit_message else "send_message",
            "text": response_text,
        }

        # Button locking: if responding to a callback with a NEW message (not editing the old one),
        # clear the markup of the previous message so the user can't click stale buttons.
        if callback_message_id and not edit_message:
            import httpx as _httpx

            async def _clear_old_markup() -> None:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageReplyMarkup"
                try:
                    async with _httpx.AsyncClient(timeout=3.0) as _client:
                        await _client.post(
                            url,
                            json={
                                "chat_id": chat_id,
                                "message_id": callback_message_id,
                                "reply_markup": {"inline_keyboard": []},
                            },
                        )
                except Exception:
                    pass  # Non-fatal: old buttons staying visible is cosmetic, not a crash

            _clear_task = asyncio.create_task(_clear_old_markup())
            _BACKGROUND_TASKS.add(_clear_task)
            _clear_task.add_done_callback(_BACKGROUND_TASKS.discard)

        send_res = await run_telegram_send(send_args)
        if send_res and send_res.sent and send_res.message_id:

            async def _save_message_id(msg_id: int) -> None:
                try:
                    db_conn = await create_db_client(DATABASE_URL)
                    await db_conn.execute(
                        "UPDATE conversation_states SET message_id = $1 WHERE chat_id = $2",
                        msg_id,
                        chat_id,
                    )
                    await db_conn.close()
                except Exception as e:
                    log_structured(logging.WARNING, "message_id_db_save_failed", chat_id=chat_id, error=str(e))
                    raise RuntimeError(f"Message ID save failed: {e}") from e

            _save_task = asyncio.create_task(_save_message_id(send_res.message_id))
            _BACKGROUND_TASKS.add(_save_task)
            _save_task.add_done_callback(_BACKGROUND_TASKS.discard)
        tg_send_ms = (time.perf_counter() - tg_outbound_start) * 1000
        await metrics.record_telegram_send_time(tg_send_ms)

        # Log completion
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        await metrics.record_processing_time(elapsed_ms)
        log_structured(
            logging.INFO,
            "update_processing_completed",
            chat_id=chat_id,
            update_id=update.update_id,
            elapsed_ms=elapsed_ms,
        )

    except Exception as e:
        tb = traceback.format_exc()
        await metrics.increment_errors()
        log_structured(
            logging.ERROR,
            "update_processing_failed",
            error=str(e),
            traceback=tb,
        )
        if "chat_id" in locals() and locals()["chat_id"]:
            with contextlib.suppress(Exception):
                await run_telegram_send(
                    {
                        "bot_token": TELEGRAM_BOT_TOKEN,
                        "chat_id": locals()["chat_id"],
                        "mode": "send_message",
                        "text": "❌ Ocurrió un error inesperado al procesar tu solicitud. Por favor reintenta.",
                    }
                )
        raise RuntimeError(f"worker job failed: {e}") from e
    finally:
        # 13. Release lock safely
        await redis.delete(lock_key)
        log_structured(logging.INFO, "worker_lock_released", chat_id=chat_id)


async def cron_auto_cancel_expired(ctx: dict[str, Any]) -> None:
    """Cron task to cancel expired pending bookings."""
    log_structured(logging.INFO, "cron_auto_cancel_expired_started")
    try:
        res = await run_auto_cancel_expired()
        log_structured(
            logging.INFO,
            "cron_auto_cancel_expired_completed",
            cancelled_count=res.get("cancelled_count", 0),
        )
    except Exception as e:
        log_structured(logging.ERROR, "cron_auto_cancel_expired_failed", error=str(e))


async def cron_gcal_reconcile(ctx: dict[str, Any]) -> None:
    """Cron task to reconcile Google Calendar events."""
    log_structured(logging.INFO, "cron_gcal_reconcile_started")
    try:
        res = await run_gcal_reconcile({})
        log_structured(
            logging.INFO,
            "cron_gcal_reconcile_completed",
            processed=res.get("processed", 0),
            synced=res.get("synced", 0),
            failed=res.get("failed", 0),
        )
    except Exception as e:
        log_structured(logging.ERROR, "cron_gcal_reconcile_failed", error=str(e))


class WorkerSettings:
    """Settings required by arq CLI."""

    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    functions: ClassVar[list[Any]] = [process_telegram_update]
    cron_jobs: ClassVar[list[Any]] = [
        cron(cron_auto_cancel_expired, unique=True, minute=None),  # Every minute
        cron(cron_gcal_reconcile, unique=True, minute=set(range(0, 60, 5))),  # Every 5 minutes
    ]
    on_startup = startup
    on_shutdown = shutdown
