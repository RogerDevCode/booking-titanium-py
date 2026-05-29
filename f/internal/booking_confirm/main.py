# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "typing-inspection>=0.4.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0",
#   "wmill>=1.693.3",
# ]
# ///
from __future__ import annotations

import asyncio
import contextlib
import json
import traceback
from datetime import datetime, timedelta
from typing import Final

from pydantic import BaseModel

from ...services.booking._booking_errors import (
    BookingClientAlreadyActiveError,
    BookingError,
    BookingMissingParamsError,
    BookingNoServiceError,
)
from ...services.booking._booking_models import BookingCreateRequest, BookingResult
from ...services.booking.core import create_booking
from ...services.booking.repo import PgBookingRepo
from .._conversation_tx import invalidate_cache, read_state, write_state
from .._db_client import create_db_client
from .._nlu_cache import ensure_nlu_cache, get_nlu_rule
from .._redis_client import create_redis_client
from .._result import DBClient, with_tenant_context
from .._wmill_adapter import log

MODULE: Final[str] = "booking_confirm"


class BookingConfirmOutput(BaseModel):
    success: bool
    booking_short_id: str | None = None
    provider_name: str | None = None
    service_name: str | None = None
    start_time: str | None = None
    booking_id: str | None = None
    user_message: str | None = None
    error: str | None = None


def _user_message(err: Exception | str) -> str:
    msg = str(err).lower()
    if "duplicate" in msg or "unique" in msg or "already" in msg or "slot unavailable" in msg:
        return str(
            get_nlu_rule(
                "msg_slot_taken", "Ese horario ya fue reservado por otra persona. Por favor elige un horario diferente."
            )
        )
    if "client_has_overlapping_booking" in msg or isinstance(err, BookingClientAlreadyActiveError):
        return str(
            get_nlu_rule(
                "msg_already_booked", "Ya tienes una hora agendada. Cancela la hora actual antes de reservar una nueva."
            )
        )
    if "no_service_for_provider" in msg or isinstance(err, BookingNoServiceError):
        return str(
            get_nlu_rule(
                "msg_no_service",
                "El profesional seleccionado no tiene servicios disponibles. Intenta con otro profesional.",
            )
        )
    return str(
        get_nlu_rule(
            "msg_generic", "No pudimos confirmar tu hora en este momento. Por favor intenta de nuevo en unos minutos."
        )
    )


async def _resolve_service(db: DBClient, provider_id: str) -> tuple[str, int]:
    row = await db.fetchrow(
        "SELECT service_id, duration_minutes FROM services WHERE provider_id = $1::uuid AND is_active = true LIMIT 1",
        provider_id,
    )
    if not row:
        raise BookingNoServiceError(f"no_service_for_provider:{provider_id}")
    return str(row["service_id"]), int(str(row["duration_minutes"]))


async def _insert_dlq(
    conn: DBClient,
    *,
    provider_id: str,
    service_id: str,
    chat_id: str,
    start_time: str,
    idempotency_key: str,
    client_id: str,
    error: Exception,
) -> None:
    try:
        try:
            parsed_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            parsed_start = datetime.now()

        await conn.execute(
            """
            INSERT INTO booking_dlq (
                provider_id, service_id, chat_id, start_time,
                idempotency_key, original_payload, failure_reason, last_error_message, status
            ) VALUES ($1::uuid, $2::uuid, $3, $4::timestamptz, $5, $6::jsonb, $7, $8, 'pending')
            """,
            provider_id,
            service_id,
            chat_id,
            parsed_start,
            idempotency_key,
            json.dumps(
                {"client_id": client_id, "provider_id": provider_id, "start_time": start_time, "chat_id": chat_id}
            ),
            "confirm_failure",
            str(error),
        )
    except Exception as dlq_err:
        log("DLQ_INSERT_FAILED", error=str(dlq_err), module=MODULE)


async def _confirm_booking_core(
    conn: DBClient,
    *,
    client_id: str,
    provider_id: str,
    service_id: str,
    duration: int,
    start_time: str,
    chat_id: str,
    version: int | None = None,
) -> BookingConfirmOutput:
    try:
        parsed_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BookingMissingParamsError(f"invalid_start_time:{start_time}") from exc

    parsed_end = parsed_start + timedelta(minutes=duration)
    idempotency_key = f"tg:{chat_id}:{start_time}"

    input_data = BookingCreateRequest.model_validate(
        {
            "client_id": client_id,
            "provider_id": provider_id,
            "service_id": service_id,
            "start_time": parsed_start,
            "end_time": parsed_end,
            "idempotency_key": idempotency_key,
            "notes": "Reservado via Telegram webhook",
        }
    )

    log("CALLING_BOOK_CREATE", idempotency_key=idempotency_key, module=MODULE)
    repo = PgBookingRepo(conn)

    async def operation() -> BookingResult:
        # ── Advisory lock: serialize all ops for this chat_id ────────────
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1::text))",
            chat_id,
        )

        # ── Verify FSM state is 'confirming' (inside the lock) ──────────
        state = await read_state(conn, chat_id)
        if version is not None and state.version != version:
            raise BookingMissingParamsError(f"state_version_mismatch:expected={version},actual={state.version}")
        current_name = state.booking_state.get("name", "unknown")
        if current_name != "confirming":
            log(
                "CONFIRM_SKIPPED_NOT_IN_CONFIRMING",
                actual_state=current_name,
                chat_id=chat_id,
                module=MODULE,
            )
            raise BookingMissingParamsError(f"not_in_confirming_state:actual={current_name}")

        # ── Create booking (same transaction) ───────────────────────────
        active = await repo.get_active_booking_for_client(client_id, provider_id)
        if active:
            raise BookingClientAlreadyActiveError("client_already_has_active_booking")
        result = await create_booking(input_data, repo)

        # ── Transition FSM to idle (same transaction) ───────────────────
        state.booking_state = {"name": "idle"}
        state.active_flow = None
        state.booking_draft = None
        state.pending_data = {
            "router_handled": True,
            "user_id": client_id,
            "client_id": client_id,
        }
        await write_state(conn, state)

        return result

    result = await with_tenant_context(conn, provider_id, operation)

    if not result or not result.booking_id:
        raise RuntimeError("no_result_from_booking_create")

    booking_id = str(result.booking_id)
    names_row = await conn.fetchrow(
        "SELECT p.name AS provider_name, s.name AS service_name "
        "FROM providers p JOIN services s ON s.provider_id = p.provider_id "
        "WHERE p.provider_id = $1::uuid AND s.service_id = $2::uuid LIMIT 1",
        provider_id,
        service_id,
    )

    log("BOOKING_CONFIRM_OK", booking_id=booking_id, chat_id=chat_id, module=MODULE)
    return BookingConfirmOutput(
        success=True,
        booking_id=booking_id,
        booking_short_id=(lambda r: f"{r[:2]}-{r[2:5]}-{r[5:8]}")(booking_id[:8].upper()),
        provider_name=str(names_row["provider_name"] if names_row else "Profesional"),
        service_name=str(names_row["service_name"] if names_row else "Servicio"),
        start_time=str(start_time),
    )


async def _main_async(
    client_id: str | None = None,
    provider_id: str | None = None,
    start_time: str | None = None,
    chat_id: str | None = None,
    pg_url: str | None = None,
    redis_url: str | None = None,
    version: int | None = None,
) -> dict[str, object]:
    log("BOOKING_CONFIRM_START", chat_id=chat_id, provider_id=provider_id, start_time=start_time, module=MODULE)

    if not client_id or not provider_id or not start_time or not chat_id:
        log(
            "BOOKING_CONFIRM_MISSING_PARAMS",
            client_id=client_id,
            provider_id=provider_id,
            start_time=start_time,
            chat_id=chat_id,
            module=MODULE,
        )
        raise BookingMissingParamsError("client_id, provider_id, start_time, chat_id required")

    await ensure_nlu_cache()
    conn = await create_db_client(pg_url)
    service_id: str | None = None
    try:
        service_id, duration = await _resolve_service(conn, provider_id)
        output = await _confirm_booking_core(
            conn,
            client_id=client_id,
            provider_id=provider_id,
            service_id=service_id,
            duration=duration,
            start_time=start_time,
            chat_id=chat_id,
            version=version,
        )

        # ── Cache invalidation AFTER successful commit ───────────────────
        if output.success:
            try:
                redis = await create_redis_client(redis_url)
                await invalidate_cache(redis, chat_id)
                await redis.aclose()
            except Exception:
                pass  # Non-fatal: cache expires via TTL

        return output.model_dump()
    except BookingError as err:
        # Business error: specific message to user, no DLQ
        log("BOOKING_CONFIRM_BUSINESS_ERROR", error=str(err), chat_id=chat_id, module=MODULE)
        return BookingConfirmOutput(success=False, error=str(err), user_message=_user_message(err)).model_dump()
    except Exception as err:
        # Infrastructure error: DLQ (only if service resolved) + generic message
        log(
            "BOOKING_CONFIRM_INFRA_ERROR",
            error=str(err),
            traceback=traceback.format_exc(),
            chat_id=chat_id,
            module=MODULE,
        )
        if service_id:
            await _insert_dlq(
                conn,
                provider_id=provider_id,
                service_id=service_id,
                chat_id=chat_id,
                start_time=start_time,
                idempotency_key=f"tg:{chat_id}:{start_time}",
                client_id=client_id,
                error=err,
            )
        return BookingConfirmOutput(success=False, error=str(err), user_message=_user_message(err)).model_dump()
    finally:
        await conn.close()


def main(
    client_id: str | None = None,
    provider_id: str | None = None,
    start_time: str | None = None,
    chat_id: str | None = None,
    pg_url: str | None = None,
    redis_url: str | None = None,
    version: int | None = None,
) -> dict[str, object]:
    try:
        return asyncio.run(
            _main_async(
                client_id=client_id,
                provider_id=provider_id,
                start_time=start_time,
                chat_id=chat_id,
                pg_url=pg_url,
                redis_url=redis_url,
                version=version,
            )
        )
    except Exception as e:
        tb = traceback.format_exc()
        with contextlib.suppress(Exception):
            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        raise RuntimeError(f"Execution failed: {e}") from e
