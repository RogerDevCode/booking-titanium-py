from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internal._result import DBClient
    from ._logger_models import InputSchema, LogResult


async def persist_log(db: DBClient, input_data: InputSchema) -> LogResult:
    try:
        rows = await db.fetch(
            """
            INSERT INTO conversations (
              client_id, channel, direction, content, intent, metadata, provider_id
            ) VALUES (
              $1::uuid, $2, $3, $4, $5, $6::jsonb, $7::uuid
            ) RETURNING message_id
            """,
            input_data.client_id,
            input_data.channel,
            input_data.direction,
            input_data.content,
            input_data.intent,
            json.dumps(input_data.metadata),
            input_data.provider_id,
        )

        if not rows:
            raise RuntimeError("db_insert_failed: No message_id returned")

        res: LogResult = {"message_id": str(rows[0]["message_id"])}
        return res
    except Exception as e:
        raise RuntimeError(f"persistence_error: {e}") from e
