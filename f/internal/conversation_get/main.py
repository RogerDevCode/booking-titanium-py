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
from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from typing import Final, cast

from .._conversation_tx import read_state
from .._db_client import create_db_client
from .._redis_client import REDIS_TTL, create_redis_client
from .._wmill_adapter import log
from ._conversation_models import ConversationGetResult, ConversationState

MODULE: Final[str] = "conversation_get"


def _normalize_lua_empty_lists(data: dict[str, object]) -> None:
    """Fix cjson Lua serialization of empty arrays as empty dicts."""
    for field_key in ("booking_state", "booking_draft"):
        if field_key in data and isinstance(data[field_key], dict):
            container = cast("dict[str, object]", data[field_key])
            if "items" in container and isinstance(container["items"], dict) and not container["items"]:
                container["items"] = []


def _snapshot_to_state(chat_id: str, data: dict[str, object]) -> ConversationState:
    """Convert a raw dict to ConversationState model."""
    return ConversationState(
        chat_id=chat_id,
        active_flow=cast("str | None", data.get("active_flow")),
        flow_step=cast("int", data.get("flow_step", 0)),
        pending_data=cast("dict[str, object]", data.get("pending_data", {})),
        booking_state=cast("dict[str, object] | None", data.get("booking_state")),
        booking_draft=cast("dict[str, object] | None", data.get("booking_draft")),
        message_id=cast("int | None", data.get("message_id")),
        version=cast("int", data.get("version", 1)),
        updated_at=cast("str", data.get("updated_at", datetime.now(UTC).isoformat())),
    )


async def _get_conversation(
    chat_id: str,
    redis_url: str | None = None,
    pg_url: str | None = None,
) -> ConversationGetResult:
    # ── 1. Try Redis cache first ─────────────────────────────────────────────
    key = f"booking:conv:{chat_id}"
    redis = await create_redis_client(redis_url)
    try:
        raw = await redis.get(key)

        if raw:
            try:
                data = cast("dict[str, object]", json.loads(str(raw)))
                _normalize_lua_empty_lists(data)
                return ConversationGetResult(data=_snapshot_to_state(chat_id, data))
            except Exception as parse_err:
                log("CACHE_PARSE_ERROR_FALLBACK_PG", error=str(parse_err), chat_id=chat_id, module=MODULE)
                # Fall through to Postgres
    except Exception as redis_err:
        log("REDIS_READ_FAILED_FALLBACK_PG", error=str(redis_err), chat_id=chat_id, module=MODULE)
        # Fall through to Postgres
    finally:
        await redis.aclose()

    # ── 2. Cache MISS or Redis down → rebuild from Postgres ──────────────────
    conn = await create_db_client(pg_url)
    try:
        await conn.execute("BEGIN")
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1::text))",
            chat_id,
        )
        snapshot = await read_state(conn, chat_id)

        if snapshot.is_new:
            await conn.execute("COMMIT")
            return ConversationGetResult(data=None)

        now = datetime.now(UTC).isoformat()
        state_dict: dict[str, object] = {
            "booking_state": snapshot.booking_state,
            "active_flow": snapshot.active_flow,
            "booking_draft": snapshot.booking_draft,
            "pending_data": snapshot.pending_data,
            "message_id": snapshot.message_id,
            "version": snapshot.version,
            "updated_at": now,
        }
        state = _snapshot_to_state(chat_id, state_dict)

        # ── 3. Refill cache (write-through, best-effort) ────────────────────
        try:
            redis2 = await create_redis_client(redis_url)
            await redis2.set(key, json.dumps(cast("dict[str, object]", state.model_dump())), ex=REDIS_TTL)
            await redis2.aclose()
        except Exception:
            pass  # Cache refill failure is non-fatal

        await conn.execute("COMMIT")
        return ConversationGetResult(data=state)

    except Exception as pg_err:
        with contextlib.suppress(Exception):
            await conn.execute("ROLLBACK")
        log("PG_READ_ERROR", error=str(pg_err), chat_id=chat_id, module=MODULE)
        raise RuntimeError(f"conversation_get pg_error: {pg_err}") from pg_err
    finally:
        await conn.close()


async def _main_async(
    chat_id: str,
    redis_url: str | None = None,
    pg_url: str | None = None,
) -> dict[str, object]:
    """Windmill entrypoint."""
    result = await _get_conversation(chat_id, redis_url, pg_url)
    return cast("dict[str, object]", result.model_dump())


def main(
    chat_id: str,
    redis_url: str | None = None,
    pg_url: str | None = None,
) -> dict[str, object]:
    import asyncio
    import traceback

    try:
        return asyncio.run(_main_async(chat_id, redis_url, pg_url))
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from .._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
