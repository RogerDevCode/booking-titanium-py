from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._provider_models import InputSchema, ProviderRow


def map_row_to_provider(row: object) -> ProviderRow:
    r = cast("dict[str, object]", row)
    return {
        "id": str(r["id"]),
        "honorific_id": str(r["honorific_id"]) if r.get("honorific_id") else None,
        "name": str(r["name"]),
        "email": str(r["email"]),
        "specialty_id": str(r["specialty_id"]) if r.get("specialty_id") else None,
        "timezone_id": int(cast("int", r["timezone_id"])) if r.get("timezone_id") is not None else None,
        "phone_app": str(r["phone_app"]) if r.get("phone_app") else None,
        "phone_contact": str(r["phone_contact"]) if r.get("phone_contact") else None,
        "telegram_chat_id": str(r["telegram_chat_id"]) if r.get("telegram_chat_id") else None,
        "gcal_calendar_id": str(r["gcal_calendar_id"]) if r.get("gcal_calendar_id") else None,
        "address_street": str(r["address_street"]) if r.get("address_street") else None,
        "address_number": str(r["address_number"]) if r.get("address_number") else None,
        "address_complement": str(r["address_complement"]) if r.get("address_complement") else None,
        "address_sector": str(r["address_sector"]) if r.get("address_sector") else None,
        "region_id": int(cast("int", r["region_id"])) if r.get("region_id") is not None else None,
        "commune_id": int(cast("int", r["commune_id"])) if r.get("commune_id") is not None else None,
        "is_active": bool(r["is_active"]),
        "has_password": bool(r.get("has_password", False)),
        "last_password_change": str(r["last_password_change"]) if r.get("last_password_change") else None,
        "created_at": str(r["created_at"]) if r.get("created_at") else "",
        "updated_at": str(r["updated_at"]) if r.get("updated_at") else "",
        "honorific_label": str(r["honorific_label"]) if r.get("honorific_label") else None,
        "specialty_name": str(r["specialty_name"]) if r.get("specialty_name") else None,
        "timezone_name": str(r["timezone_name"]) if r.get("timezone_name") else None,
        "region_name": str(r["region_name"]) if r.get("region_name") else None,
        "commune_name": str(r["commune_name"]) if r.get("commune_name") else None,
    }


async def list_providers(db: DBClient) -> list[ProviderRow]:
    try:
        rows = await db.fetch(
            """
            SELECT p.*,
                   h.label as honorific_label,
                   s.name as specialty_name,
                   tz.name as timezone_name,
                   r.name as region_name,
                   c.name as commune_name,
                   (p.password_hash IS NOT NULL) as has_password
            FROM providers p
            LEFT JOIN admin_honorifics h ON p.honorific_id = h.honorific_id
            LEFT JOIN admin_specialties s ON p.specialty_id = s.specialty_id
            LEFT JOIN admin_timezones tz ON p.timezone_id = tz.timezone_id
            LEFT JOIN admin_regions r ON p.region_id = r.region_id
            LEFT JOIN admin_communes c ON p.commune_id = c.commune_id
            ORDER BY p.name ASC
            """
        )
        return [map_row_to_provider(r) for r in rows]
    except Exception as e:
        raise RuntimeError(f"db_error: {e}") from e


async def create_provider(db: DBClient, input_data: InputSchema) -> ProviderRow:
    if not input_data.name or not input_data.email:
        raise RuntimeError("missing_fields: name and email are required")

    try:
        rows = await db.fetch(
            """
            INSERT INTO providers (
                name, email, honorific_id, specialty_id, timezone_id,
                phone_app, phone_contact, telegram_chat_id, gcal_calendar_id,
                address_street, address_number, address_complement, address_sector,
                region_id, commune_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING *, (password_hash IS NOT NULL) as has_password,
                      NULL as honorific_label, NULL as specialty_name, NULL as timezone_name,
                      NULL as region_name, NULL as commune_name
            """,
            input_data.name,
            input_data.email,
            input_data.honorific_id,
            input_data.specialty_id,
            input_data.timezone_id,
            input_data.phone_app,
            input_data.phone_contact,
            input_data.telegram_chat_id,
            input_data.gcal_calendar_id,
            input_data.address_street,
            input_data.address_number,
            input_data.address_complement,
            input_data.address_sector,
            input_data.region_id,
            input_data.commune_id,
        )
        if not rows:
            raise RuntimeError("insert_failed")
        return map_row_to_provider(rows[0])
    except Exception as e:
        raise RuntimeError(f"db_error: {e}") from e


async def update_provider(db: DBClient, input_data: InputSchema) -> ProviderRow:
    if not input_data.provider_id:
        raise RuntimeError("missing_provider_id")

    try:
        rows = await db.fetch(
            """
            UPDATE providers
            SET name = COALESCE($1, name),
                email = COALESCE($2, email),
                honorific_id = COALESCE($3, honorific_id),
                specialty_id = COALESCE($4, specialty_id),
                timezone_id = COALESCE($5, timezone_id),
                phone_app = COALESCE($6, phone_app),
                phone_contact = COALESCE($7, phone_contact),
                telegram_chat_id = COALESCE($8, telegram_chat_id),
                gcal_calendar_id = COALESCE($9, gcal_calendar_id),
                address_street = COALESCE($10, address_street),
                address_number = COALESCE($11, address_number),
                address_complement = COALESCE($12, address_complement),
                address_sector = COALESCE($13, address_sector),
                region_id = COALESCE($14, region_id),
                commune_id = COALESCE($15, commune_id),
                is_active = COALESCE($16, is_active),
                updated_at = NOW()
            WHERE provider_id = $17::uuid
            RETURNING *, (password_hash IS NOT NULL) as has_password,
                      NULL as honorific_label, NULL as specialty_name, NULL as timezone_name,
                      NULL as region_name, NULL as commune_name
            """,
            input_data.name,
            input_data.email,
            input_data.honorific_id,
            input_data.specialty_id,
            input_data.timezone_id,
            input_data.phone_app,
            input_data.phone_contact,
            input_data.telegram_chat_id,
            input_data.gcal_calendar_id,
            input_data.address_street,
            input_data.address_number,
            input_data.address_complement,
            input_data.address_sector,
            input_data.region_id,
            input_data.commune_id,
            input_data.is_active,
            input_data.provider_id,
        )
        if not rows:
            raise RuntimeError("update_failed_or_not_found")
        return map_row_to_provider(rows[0])
    except Exception as e:
        raise RuntimeError(f"db_error: {e}") from e


async def reset_provider_password(db: DBClient, provider_id: str) -> ProviderRow:
    import secrets
    import string

    from ..internal._crypto import hash_password

    try:
        chars = string.ascii_letters + string.digits
        temp_pwd = "".join(secrets.choice(chars) for _ in range(8))
        pwd_hash = hash_password(temp_pwd)

        rows = await db.fetch(
            """
            UPDATE providers
            SET password_hash = $1,
                last_password_change = NOW(),
                updated_at = NOW()
            WHERE provider_id = $2::uuid
            RETURNING *, (password_hash IS NOT NULL) as has_password,
                      NULL as honorific_label, NULL as specialty_name, NULL as timezone_name,
                      NULL as region_name, NULL as commune_name
            """,
            pwd_hash,
            provider_id,
        )
        if not rows:
            raise RuntimeError("provider_not_found")
        return map_row_to_provider(rows[0])
    except Exception as e:
        raise RuntimeError(f"db_error: {e}") from e
