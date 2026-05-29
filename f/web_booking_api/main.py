# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0"
# ]
# ///
import asyncio

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Web Booking API orchestrator (crear/cancelar/reagendar)
# DB Tables Used  : providers, services, bookings, clients, users
# Concurrency Risk: YES — uses FOR UPDATE on provider
# GCal Calls      : NO — handled by async sync
# Idempotency Key : YES — deterministic derivation
# RLS Tenant ID   : YES — with_tenant_context wraps all ops
# Pydantic Schemas: YES — InputSchema validates parameters
# ============================================================================
from typing import Any, cast

from ..internal._db_client import create_db_client
from ..internal._result import with_tenant_context
from ..internal._wmill_adapter import log
from ._booking_logic import BookingRepository, calculate_end_time, derive_idempotency_key
from ._booking_models import BookingResult, InputSchema

MODULE = "web_booking_api"


async def _main_async(args: dict[str, Any]) -> dict[str, object]:
    # 1. Validate Input
    try:
        input_data = InputSchema.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"error_validacion: {e}") from e

    conn = await create_db_client()
    try:
        repo = BookingRepository(conn)

        # 2. Resolve Tenant Context
        tenant_id: str
        if input_data.action == "crear":
            if not input_data.provider_id:
                raise RuntimeError("provider_id_requerido")
            tenant_id = input_data.provider_id
        else:
            if not input_data.booking_id:
                raise RuntimeError("booking_id_requerido")
            tenant_id = await repo.resolve_tenant_for_booking(input_data.booking_id)

        # 3. Execute within Tenant Context
        async def operation() -> BookingResult:
            # 3.1 Resolve Client ID
            client_id = await repo.resolve_client_id(input_data.user_id)

            if input_data.action == "crear":
                if not input_data.service_id or not input_data.start_time:
                    raise RuntimeError("datos_insuficientes_crear")

                await repo.lock_provider(tenant_id)
                duration = await repo.get_service_duration(input_data.service_id)
                end_time = calculate_end_time(input_data.start_time, duration)
                await repo.check_overlap(tenant_id, input_data.start_time, end_time)

                ik = input_data.idempotency_key or derive_idempotency_key(
                    "crear", [tenant_id, client_id, input_data.service_id, input_data.start_time]
                )

                b = await repo.insert_booking(
                    {
                        "tenant_id": tenant_id,
                        "client_id": client_id,
                        "service_id": input_data.service_id,
                        "start_time": input_data.start_time,
                        "end_time": end_time,
                        "idempotency_key": ik,
                    }
                )

                return {"booking_id": b["booking_id"], "status": b["status"], "message": "Hora creada exitosamente"}

            elif input_data.action == "cancelar":
                if not input_data.booking_id:
                    raise RuntimeError("booking_id_requerido")
                booking = await repo.get_booking(input_data.booking_id)
                if booking["client_id"] != client_id:
                    raise RuntimeError("permiso_denegado_cita")
                if booking["status"] not in ["pending", "confirmed"]:
                    raise RuntimeError(f"estado_invalido_cancelar: {booking['status']}")

                await repo.update_status(input_data.booking_id, "cancelled", input_data.cancellation_reason)
                return {
                    "booking_id": input_data.booking_id,
                    "status": "cancelled",
                    "message": "Hora cancelada exitosamente",
                }

            elif input_data.action == "reagendar":
                if not input_data.booking_id or not input_data.start_time:
                    raise RuntimeError("datos_insuficientes_reagendar")

                old = await repo.get_booking(input_data.booking_id)
                if old["client_id"] != client_id:
                    raise RuntimeError("permiso_denegado_cita")
                if old["status"] not in ["pending", "confirmed"]:
                    raise RuntimeError("estado_invalido_reagendar")

                await repo.lock_provider(tenant_id)
                duration = await repo.get_service_duration(old["service_id"])
                end_time = calculate_end_time(input_data.start_time, duration)
                await repo.check_overlap(tenant_id, input_data.start_time, end_time, input_data.booking_id)

                ik = input_data.idempotency_key or derive_idempotency_key(
                    "reagendar", [input_data.booking_id, input_data.start_time]
                )

                b = await repo.insert_booking(
                    {
                        "tenant_id": tenant_id,
                        "client_id": client_id,
                        "service_id": old["service_id"],
                        "start_time": input_data.start_time,
                        "end_time": end_time,
                        "idempotency_key": ik,
                        "rescheduled_from": input_data.booking_id,
                    }
                )

                await repo.update_status(input_data.booking_id, "rescheduled")
                return {"booking_id": b["booking_id"], "status": b["status"], "message": "Hora reagendada exitosamente"}

            raise RuntimeError("unsupported_action")

        return cast("dict[str, object]", await with_tenant_context(conn, tenant_id, operation))

    except Exception as e:
        log("Web Booking API Internal Error", error=str(e), module=MODULE)
        raise RuntimeError(f"error_inesperado: {e}") from e
    finally:
        await conn.close()  # pyright: ignore[reportUnknownMemberType]


def main(args: InputSchema | dict[str, object]) -> dict[str, object]:
    import traceback

    from pydantic import BaseModel

    try:
        if isinstance(args, InputSchema):
            validated = args
        else:
            validated = InputSchema.model_validate(args)

        result = asyncio.run(_main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return result.model_dump()
        return result

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
