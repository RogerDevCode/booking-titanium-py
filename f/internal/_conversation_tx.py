"""Transactional conversation state manager.

Implements three production-proven pillars:
1. pg_advisory_xact_lock for per-chat serialization
2. Optimistic locking via version column
3. Cache-aside with invalidation (Redis DEL on write)

All functions assume they are called INSIDE an active transaction
with the advisory lock already held.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from ._result import DBClient

_MODULE: Final[str] = "conversation_tx"
_logger: Final[logging.Logger] = logging.getLogger(_MODULE)


class ConversationConflictError(RuntimeError):
    """Raised when optimistic lock detects concurrent modification."""


@dataclass
class ConversationSnapshot:
    """Mutable snapshot of conversation state loaded from Postgres."""

    chat_id: str
    booking_state: dict[str, Any] = field(default_factory=lambda: {"name": "idle"})
    active_flow: str | None = None
    booking_draft: dict[str, Any] | None = None
    pending_data: dict[str, Any] = field(default_factory=lambda: cast("dict[str, Any]", {}))
    message_id: int | None = None
    version: int = 0
    is_new: bool = False

    def model_dump(self) -> dict[str, Any]:
        import dataclasses

        return dataclasses.asdict(self)


def _parse_jsonb(raw: object) -> dict[str, Any]:
    """Parse a JSONB value from asyncpg (could be str or dict)."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        result = json.loads(raw)
        if isinstance(result, dict):
            return cast("dict[str, Any]", result)
        return {}
    if isinstance(raw, dict):
        return cast("dict[str, Any]", raw)
    return {}


async def read_state(conn: DBClient, chat_id: str) -> ConversationSnapshot:
    """Read current state from Postgres. Must be called inside a transaction."""
    row = await conn.fetchrow(
        "SELECT booking_state, active_flow, booking_draft, pending_data, "
        "message_id, version FROM conversation_states WHERE chat_id = $1",
        chat_id,
    )
    if not row:
        return ConversationSnapshot(chat_id=chat_id, is_new=True)

    return ConversationSnapshot(
        chat_id=chat_id,
        booking_state=_parse_jsonb(row.get("booking_state")),
        active_flow=str(row.get("active_flow")) if row.get("active_flow") else None,
        booking_draft=_parse_jsonb(row.get("booking_draft")) or None,
        pending_data=_parse_jsonb(row.get("pending_data")),
        message_id=int(str(row.get("message_id"))) if row.get("message_id") else None,
        version=int(str(row.get("version") or 1)),
    )


async def write_state(conn: DBClient, state: ConversationSnapshot) -> None:
    """Persist state to Postgres with optimistic locking.

    Must be called inside a transaction that holds the advisory lock.
    Raises ConversationConflictError if version mismatch detected.
    """
    now = datetime.now(UTC)
    bs_json = json.dumps(state.booking_state)
    bd_json = json.dumps(state.booking_draft) if state.booking_draft else None
    pd_json = json.dumps(state.pending_data)

    if state.is_new:
        await conn.execute(
            """
            INSERT INTO conversation_states
                (chat_id, booking_state, active_flow, booking_draft,
                 pending_data, message_id, version, updated_at)
            VALUES ($1, $2::jsonb, $3, $4::jsonb, $5::jsonb, $6, 1, $7::timestamptz)
            ON CONFLICT (chat_id) DO NOTHING
            """,
            state.chat_id,
            bs_json,
            state.active_flow,
            bd_json,
            pd_json,
            state.message_id,
            now,
        )
        return

    result = await conn.execute(
        """
        UPDATE conversation_states
        SET booking_state = $1::jsonb,
            active_flow = $2,
            booking_draft = $3::jsonb,
            pending_data = $4::jsonb,
            message_id = $5,
            version = version + 1,
            updated_at = $6::timestamptz
        WHERE chat_id = $7 AND version = $8
        """,
        bs_json,
        state.active_flow,
        bd_json,
        pd_json,
        state.message_id,
        now,
        state.chat_id,
        state.version,
    )

    if result == "UPDATE 0":
        raise ConversationConflictError(
            f"Optimistic lock conflict for chat_id={state.chat_id} at version={state.version}"
        )


async def invalidate_cache(redis_client: Redis, chat_id: str) -> None:
    """Delete Redis cache key (best-effort). Call AFTER Postgres COMMIT."""
    try:
        await redis_client.delete(f"booking:conv:{chat_id}")
    except Exception as exc:
        _logger.warning(
            "REDIS_CACHE_INVALIDATION_FAILED chat_id=%s error=%s",
            chat_id,
            str(exc),
        )
