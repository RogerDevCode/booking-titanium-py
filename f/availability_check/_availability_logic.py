from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._availability_models import ProviderRow


async def get_provider_service_id(db: DBClient, provider_id: str) -> str | None:
    """
    Fetches the first active service ID for a provider.
    """
    rows = await db.fetch(
        """
        SELECT service_id FROM services
        WHERE provider_id = $1::uuid AND is_active = true
        ORDER BY created_at ASC
        LIMIT 1
        """,
        provider_id,
    )
    if not rows:
        return None
    return str(rows[0]["service_id"])


async def get_provider(db: DBClient, provider_id: str) -> ProviderRow | None:
    """
    Fetches provider details including name and timezone.
    """
    rows = await db.fetch(
        """
        SELECT p.provider_id, p.name, t.name AS timezone
        FROM providers p
        LEFT JOIN timezones t ON t.id = p.timezone_id
        WHERE p.provider_id = $1::uuid AND p.is_active = true
        LIMIT 1
        """,
        provider_id,
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "provider_id": str(row["provider_id"]),
        "name": str(row["name"]),
        "timezone": str(row["timezone"]),
    }
