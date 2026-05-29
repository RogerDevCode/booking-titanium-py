from datetime import datetime

from ..internal._result import DBClient
from ._profile_models import InputSchema, ProfileRow


class ProfileRepository:
    def __init__(self, db: DBClient) -> None:
        self.db = db

    async def find_by_id(self, provider_id: str) -> ProfileRow:
        try:
            rows = await self.db.fetch(
                """
                SELECT
                  p.id, p.name, p.email, h.label AS honorific_label,
                  s.name AS specialty_name, t.name AS timezone_name,
                  p.phone_app, p.phone_contact, p.telegram_chat_id, p.gcal_calendar_id,
                  p.address_street, p.address_number, p.address_complement, p.address_sector,
                  r.name AS region_name, c.name AS commune_name,
                  p.is_active, (p.password_hash IS NOT NULL) AS has_password,
                  p.last_password_change, p.created_at, p.updated_at
                FROM providers p
                LEFT JOIN honorifics h ON h.honorific_id = p.honorific_id
                LEFT JOIN specialties s ON s.specialty_id = p.specialty_id
                LEFT JOIN timezones t ON t.id = p.timezone_id
                LEFT JOIN regions r ON r.region_id = p.region_id
                LEFT JOIN communes c ON c.commune_id = p.commune_id
                WHERE p.id = $1::uuid
                LIMIT 1
                """,
                provider_id,
            )
            if not rows:
                raise RuntimeError("profile_not_found")

            r = rows[0]
            res: ProfileRow = {
                "id": str(r["id"]),
                "name": str(r["name"]),
                "email": str(r["email"]),
                "honorific_label": str(r["honorific_label"]) if r.get("honorific_label") else None,
                "specialty_name": str(r["specialty_name"]) if r.get("specialty_name") else None,
                "timezone_name": str(r["timezone_name"]) if r.get("timezone_name") else None,
                "phone_app": str(r["phone_app"]) if r.get("phone_app") else None,
                "phone_contact": str(r["phone_contact"]) if r.get("phone_contact") else None,
                "telegram_chat_id": str(r["telegram_chat_id"]) if r.get("telegram_chat_id") else None,
                "gcal_calendar_id": str(r["gcal_calendar_id"]) if r.get("gcal_calendar_id") else None,
                "address_street": str(r["address_street"]) if r.get("address_street") else None,
                "address_number": str(r["address_number"]) if r.get("address_number") else None,
                "address_complement": str(r["address_complement"]) if r.get("address_complement") else None,
                "address_sector": str(r["address_sector"]) if r.get("address_sector") else None,
                "region_name": str(r["region_name"]) if r.get("region_name") else None,
                "commune_name": str(r["commune_name"]) if r.get("commune_name") else None,
                "is_active": bool(r["is_active"]),
                "has_password": bool(r.get("password_hash")),
                "last_password_change": r["last_password_change"].isoformat()
                if r.get("last_password_change") and isinstance(r["last_password_change"], datetime)
                else None,
            }
            return res
        except Exception as e:
            raise RuntimeError(f"fetch_profile_failed: {e}") from e

    async def update(self, provider_id: str, data: InputSchema) -> None:
        _ALLOWED = {
            "name",
            "description",
            "specialty_id",
            "phone",
            "email",
            "website",
            "photo_url",
            "address_street",
            "address_number",
            "address_complement",
            "address_sector",
            "region_id",
            "commune_id",
        }
        fields: list[str] = []
        params: list[object] = []
        idx = 1
        for f in _ALLOWED:
            val = getattr(data, f)
            if val is not None:
                fields.append(f"{f} = ${idx}")
                params.append(val)
                idx += 1

        if not fields:
            raise RuntimeError("no_changes_provided")

        params.append(provider_id)
        query = f"UPDATE providers SET {', '.join(fields)}, updated_at = NOW() WHERE id = ${idx}::uuid"
        try:
            await self.db.execute(query, *params)
        except Exception as e:
            raise RuntimeError(f"update_failed: {e}") from e

    async def get_password_hash(self, provider_id: str) -> str:
        rows = await self.db.fetch("SELECT password_hash FROM providers WHERE id = $1::uuid LIMIT 1", provider_id)
        if not rows:
            raise RuntimeError("provider_not_found")
        h = rows[0].get("password_hash")
        if not h:
            raise RuntimeError("no_password_set")
        return str(h)

    async def update_password(self, provider_id: str, new_hash: str) -> None:
        try:
            await self.db.execute(
                "UPDATE providers SET password_hash = $1, last_password_change = NOW(), updated_at = NOW() WHERE id = $2::uuid",  # noqa: E501
                new_hash,
                provider_id,
            )
        except Exception as e:
            raise RuntimeError(f"password_update_failed: {e}") from e
