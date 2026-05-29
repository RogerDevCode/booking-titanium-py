from __future__ import annotations

from typing import TYPE_CHECKING

from f.internal._date_resolver import resolve_date, resolve_time

from ._get_entity import get_entity

if TYPE_CHECKING:
    from f.internal._result import DBClient

    from ._orchestrator_models import OrchestratorInput, ResolvedContext

"""
PRE-FLIGHT
Mission          : Resolve full context (ids, date, time) from partial AI input.
DB Tables Used   : providers, services, clients, specialties
...
RLS Tenant ID    : NO — discovery mode
Zod Schemas      : NO
"""


async def resolve_context(db: DBClient, input_data: OrchestratorInput) -> ResolvedContext:
    """
    Intelligently resolves missing IDs and normalises date/time.
    """
    try:
        tenant_id: str | None = input_data.tenant_id
        client_id: str | None = input_data.client_id

        # Try to get from entities if not explicitly provided
        provider_id: str | None = input_data.provider_id or get_entity(input_data.entities, "provider_id")
        service_id: str | None = input_data.service_id or get_entity(input_data.entities, "service_id")
        res_date: str | None = input_data.date or get_entity(input_data.entities, "date")
        res_time: str | None = input_data.time or get_entity(input_data.entities, "time")

        provider_name = get_entity(input_data.entities, "provider_name")
        specialty_name = get_entity(input_data.entities, "specialty_name")

        # 1. Intelligent Provider Resolution by Name
        if not provider_id and provider_name:
            # Note: ILIKE used for case-insensitive search
            rows = await db.fetch("SELECT provider_id FROM providers WHERE name ILIKE $1 LIMIT 1", f"%{provider_name}%")
            if rows:
                provider_id = str(rows[0]["provider_id"])

        # 2. Intelligent Service Resolution by Specialty Name
        if not service_id and specialty_name:
            rows = await db.fetch(
                """
                SELECT s.service_id
                FROM services s
                JOIN providers p ON s.provider_id = p.provider_id
                JOIN specialties sp ON sp.specialty_id = p.specialty_id
                WHERE sp.name ILIKE $1
                LIMIT 1
                """,
                f"%{specialty_name}%",
            )
            if rows:
                service_id = str(rows[0]["service_id"])

        # 3. Resolve Timezone (Fail-Fast if not found)
        timezone: str | None = None
        if provider_id:
            rows = await db.fetch(
                "SELECT t.name AS timezone FROM providers p "
                "LEFT JOIN timezones t ON t.id = p.timezone_id "
                "WHERE p.provider_id = $1::uuid LIMIT 1",
                provider_id,
            )
            if rows and rows[0]["timezone"]:
                timezone = str(rows[0]["timezone"])

        # 4. Client Resolution by Telegram Chat ID
        if not client_id and input_data.telegram_chat_id:
            rows = await db.fetch(
                "SELECT c.client_id, t.name AS timezone FROM clients c "
                "LEFT JOIN timezones t ON t.id = c.timezone_id "
                "WHERE c.telegram_chat_id = $1 LIMIT 1",
                input_data.telegram_chat_id,
            )
            if rows:
                client_id = str(rows[0]["client_id"])
                if not timezone and rows[0]["timezone"]:
                    timezone = str(rows[0]["timezone"])
            else:
                # Auto-register client if chat_id known but not in DB
                name = input_data.telegram_name or "Usuario Telegram"
                # Use provider timezone as default for new client if available, else it will fail later
                client_tz = timezone or "UTC"
                rows = await db.fetch(
                    "INSERT INTO clients (name, telegram_chat_id, timezone_id) "
                    "VALUES ($1, $2, (SELECT id FROM timezones WHERE name = $3 LIMIT 1)) "
                    "RETURNING client_id",
                    name,
                    input_data.telegram_chat_id,
                    client_tz,
                )
                if rows:
                    client_id = str(rows[0]["client_id"])

        if not timezone and client_id:
            rows = await db.fetch(
                "SELECT t.name AS timezone FROM clients c "
                "LEFT JOIN timezones t ON t.id = c.timezone_id "
                "WHERE c.client_id = $1::uuid LIMIT 1",
                client_id,
            )
            if rows and rows[0]["timezone"]:
                timezone = str(rows[0]["timezone"])

        if not timezone:
            raise RuntimeError("Timezone resolution failed. A provider or client with a valid timezone is required.")

        # 5. Date/Time Parsing
        if res_date:
            abs_date = resolve_date(res_date, {"timezone": timezone})
            if abs_date:
                res_date = abs_date

        if res_time:
            abs_time = resolve_time(res_time)
            if abs_time:
                res_time = abs_time

        # 6. Tenant Fallback
        # If no tenant is provided, we pick the first one as default or from the resolved provider
        if not tenant_id:
            if provider_id:
                tenant_id = provider_id
            else:
                rows = await db.fetch("SELECT provider_id FROM providers LIMIT 1")
                if rows:
                    tenant_id = str(rows[0]["provider_id"])
                    provider_id = tenant_id

        if not tenant_id:
            raise RuntimeError("Could not resolve tenant_id")

        # 7. Service Fallback (Pick first service of the provider)
        if not service_id and provider_id:
            rows = await db.fetch("SELECT service_id FROM services WHERE provider_id = $1::uuid LIMIT 1", provider_id)
            if rows:
                service_id = str(rows[0]["service_id"])

        res: ResolvedContext = {
            "tenantId": tenant_id,
            "clientId": client_id,
            "providerId": provider_id,
            "serviceId": service_id,
            "date": res_date,
            "time": res_time,
        }
        return res
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Context resolution error: {e}") from e
