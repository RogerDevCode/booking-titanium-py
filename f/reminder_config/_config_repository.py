from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from ._config_service import default_preferences, parse_preferences_payload

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._config_models import ReminderPreferences


async def load_preferences(db: DBClient, client_id: str) -> ReminderPreferences:
    rows = await db.fetch("SELECT metadata FROM clients WHERE client_id = $1::uuid LIMIT 1", client_id)
    if not rows:
        return default_preferences()

    metadata_raw = rows[0].get("metadata")
    if metadata_raw is None:
        return default_preferences()

    metadata_obj: dict[str, object]
    if isinstance(metadata_raw, str):
        metadata_obj = cast("dict[str, object]", json.loads(metadata_raw))
    elif isinstance(metadata_raw, dict):
        metadata_obj = cast("dict[str, object]", metadata_raw)
    else:
        metadata_obj = {}

    raw_preferences: object = metadata_obj.get("reminder_preferences")
    if raw_preferences is not None and not isinstance(raw_preferences, dict):
        return default_preferences()
    return parse_preferences_payload(cast("dict[str, object] | None", raw_preferences))


async def save_preferences(db: DBClient, client_id: str, preferences: ReminderPreferences) -> None:
    await db.execute(
        """
        UPDATE clients
        SET metadata = jsonb_set(
              COALESCE(metadata, '{}'::jsonb),
              '{reminder_preferences}',
              $1::jsonb
            ),
            updated_at = NOW()
        WHERE client_id = $2::uuid
        """,
        preferences.model_dump_json(),
        client_id,
    )
