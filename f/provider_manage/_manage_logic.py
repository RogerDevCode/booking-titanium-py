from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._manage_models import InputSchema


async def handle_provider_actions(db: DBClient, input_data: InputSchema) -> dict[str, object]:
    action = input_data.action
    if action == "create_provider":
        if not input_data.name or not input_data.email:
            raise RuntimeError("MISSING_FIELDS: name and email are required")
        rows = await db.fetch(
            """
            INSERT INTO providers (name, email, phone, specialty_id, timezone_id)
            VALUES ($1, $2, $3, $4::uuid, $5)
            RETURNING provider_id, name
            """,
            input_data.name,
            input_data.email,
            input_data.phone,
            input_data.specialty_id,
            input_data.timezone_id,
        )
        if not rows:
            raise RuntimeError("DATABASE_ERROR: Failed to create provider")
        res_create: dict[str, object] = {
            "created": True,
            "provider_id": str(rows[0]["provider_id"]),
            "name": str(rows[0]["name"]),
        }
        return res_create

    elif action == "update_provider":
        if not input_data.provider_id:
            raise RuntimeError("MISSING_FIELDS: provider_id is required")
        await db.execute(
            """
            UPDATE providers
            SET name = COALESCE($1, name),
                phone = COALESCE($2, phone),
                specialty_id = COALESCE($3::uuid, specialty_id),
                timezone_id = COALESCE($4, timezone_id),
                is_active = COALESCE($5, is_active),
                updated_at = NOW()
            WHERE provider_id = $6::uuid
            """,
            input_data.name,
            input_data.phone,
            input_data.specialty_id,
            input_data.timezone_id,
            input_data.is_active,
            input_data.provider_id,
        )
        res_upd: dict[str, object] = {"updated": True}
        return res_upd

    elif action == "list_providers":
        rows = await db.fetch(
            "SELECT provider_id, name, email, phone, specialty_id, timezone_id, is_active "
            "FROM providers ORDER BY name ASC"
        )
        res_list: dict[str, object] = {"providers": [dict(r) for r in rows]}
        return res_list

    raise RuntimeError(f"ROUTING_ERROR: Action {action} not handled by Provider handler")


async def handle_service_actions(db: DBClient, input_data: InputSchema) -> dict[str, object]:
    action = input_data.action
    if action == "create_service":
        if not input_data.provider_id or not input_data.service_name:
            raise RuntimeError("MISSING_FIELDS: provider_id and service_name are required")
        rows = await db.fetch(
            """
            INSERT INTO services (provider_id, name, description, duration_minutes, buffer_minutes, price_cents, currency)  # noqa: E501
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
            RETURNING service_id, name
            """,  # noqa: E501
            input_data.provider_id,
            input_data.service_name,
            input_data.description,
            input_data.duration_minutes or 30,
            input_data.buffer_minutes or 10,
            input_data.price_cents or 0,
            input_data.currency or "MXN",
        )
        if not rows:
            raise RuntimeError("DATABASE_ERROR: Failed to create service")
        res_create: dict[str, object] = {
            "created": True,
            "service_id": str(rows[0]["service_id"]),
            "name": str(rows[0]["name"]),
        }
        return res_create

    elif action == "update_service":
        if not input_data.service_id:
            raise RuntimeError("MISSING_FIELDS: service_id is required")
        await db.execute(
            """
            UPDATE services
            SET name = COALESCE($1, name),
                description = COALESCE($2, description),
                duration_minutes = COALESCE($3, duration_minutes),
                buffer_minutes = COALESCE($4, buffer_minutes),
                price_cents = COALESCE($5, price_cents),
                currency = COALESCE($6, currency),
                is_active = COALESCE($7, is_active)
            WHERE service_id = $8::uuid
            """,
            input_data.service_name,
            input_data.description,
            input_data.duration_minutes,
            input_data.buffer_minutes,
            input_data.price_cents,
            input_data.currency,
            input_data.is_active,
            input_data.service_id,
        )
        res_upd: dict[str, object] = {"updated": True}
        return res_upd

    elif action == "list_services":
        rows = await db.fetch(
            """
            SELECT s.service_id, s.name, s.description, s.duration_minutes, s.buffer_minutes,
                   s.price_cents, s.currency, s.is_active, p.name as provider_name
            FROM services s JOIN providers p ON p.provider_id = s.provider_id
            ORDER BY p.name, s.name ASC
            """
        )
        res_list: dict[str, object] = {"services": [dict(r) for r in rows]}
        return res_list

    raise RuntimeError(f"ROUTING_ERROR: Action {action} not handled by Service handler")


async def handle_schedule_actions(db: DBClient, input_data: InputSchema) -> dict[str, object]:
    action = input_data.action
    if action == "set_schedule":
        if (
            input_data.provider_id is None
            or input_data.day_of_week is None
            or not input_data.start_time
            or not input_data.end_time
        ):
            raise RuntimeError("MISSING_FIELDS: provider_id, day_of_week, start_time, end_time are required")

        try:
            t_start = time.fromisoformat(input_data.start_time)
            t_end = time.fromisoformat(input_data.end_time)
        except ValueError:
            raise RuntimeError("INVALID_TIME_FORMAT") from None

        await db.execute(
            """
            INSERT INTO provider_schedules (provider_id, day_of_week, start_time, end_time, is_active)
            VALUES ($1::uuid, $2, $3::time, $4::time, true)
            ON CONFLICT (provider_id, day_of_week, start_time)
            DO UPDATE SET end_time = EXCLUDED.end_time, is_active = true
            """,
            input_data.provider_id,
            input_data.day_of_week,
            t_start,
            t_end,
        )
        res_upd: dict[str, object] = {"updated": True}
        return res_upd

    elif action == "remove_schedule":
        if input_data.provider_id is None or input_data.day_of_week is None:
            raise RuntimeError("MISSING_FIELDS: provider_id and day_of_week are required")
        await db.execute(
            "UPDATE provider_schedules SET is_active = false WHERE provider_id = $1::uuid AND day_of_week = $2",
            input_data.provider_id,
            input_data.day_of_week,
        )
        res_de: dict[str, object] = {"deactivated": True}
        return res_de

    raise RuntimeError(f"ROUTING_ERROR: Action {action} not handled by Schedule handler")


async def handle_override_actions(db: DBClient, input_data: InputSchema) -> dict[str, object]:
    action = input_data.action
    if action == "set_override":
        if not input_data.provider_id or not input_data.override_date:
            raise RuntimeError("MISSING_FIELDS: provider_id and override_date are required")

        try:
            d_override = date.fromisoformat(input_data.override_date)
            t_start = time.fromisoformat(input_data.start_time) if input_data.start_time else None
            t_end = time.fromisoformat(input_data.end_time) if input_data.end_time else None
        except ValueError:
            raise RuntimeError("INVALID_DATE_OR_TIME_FORMAT") from None

        await db.execute(
            """
            INSERT INTO schedule_overrides (provider_id, override_date, is_blocked, start_time, end_time, reason)
            VALUES ($1::uuid, $2::date, $3, $4::time, $5::time, $6)
            ON CONFLICT (provider_id, override_date)
            DO UPDATE SET is_blocked = EXCLUDED.is_blocked,
                          start_time = EXCLUDED.start_time,
                          end_time = EXCLUDED.end_time,
                          reason = EXCLUDED.reason
            """,
            input_data.provider_id,
            d_override,
            input_data.is_blocked or False,
            t_start,
            t_end,
            input_data.override_reason,
        )
        res_upd: dict[str, object] = {"updated": True}
        return res_upd

    elif action == "remove_override":
        if not input_data.provider_id or not input_data.override_date:
            raise RuntimeError("MISSING_FIELDS: provider_id and override_date are required")

        try:
            d_override = date.fromisoformat(input_data.override_date)
        except ValueError:
            raise RuntimeError("INVALID_DATE_FORMAT") from None

        await db.execute(
            "DELETE FROM schedule_overrides WHERE provider_id = $1::uuid AND override_date = $2::date",
            input_data.provider_id,
            d_override,
        )
        res_del: dict[str, object] = {"deleted": True}
        return res_del

    raise RuntimeError(f"ROUTING_ERROR: Action {action} not handled by Override handler")
