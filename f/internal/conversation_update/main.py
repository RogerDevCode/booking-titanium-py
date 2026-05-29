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
from typing import Final

from .._conversation_tx import ConversationConflictError, invalidate_cache, read_state, write_state
from .._db_client import create_db_client
from .._redis_client import create_redis_client
from .._wmill_adapter import log
from ._update_models import ConversationUpdateInput, ConversationUpdateResult

MODULE: Final[str] = "conversation_update"


async def _update_conversation(
    input_data: ConversationUpdateInput,
    redis_url: str | None = None,
    pg_url: str | None = None,
) -> ConversationUpdateResult:
    conn = await create_db_client(pg_url)
    redis = await create_redis_client(redis_url)

    try:
        # ── BEGIN + advisory lock (serializes all ops for this chat_id) ───────
        await conn.execute("BEGIN")
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext($1::text))",
            input_data.chat_id,
        )

        if input_data.clear:
            await conn.execute(
                "DELETE FROM conversation_states WHERE chat_id = $1",
                input_data.chat_id,
            )
            await conn.execute("COMMIT")
            # Invalidate cache after commit
            await invalidate_cache(redis, input_data.chat_id)
            return ConversationUpdateResult(success=True, chat_id=input_data.chat_id)

        # ── Read current state (serialized by advisory lock) ─────────────────
        state = await read_state(conn, input_data.chat_id)

        # ── Verify optimistic locking ────────────────────────────────────────
        if input_data.version is not None and state.version != input_data.version:
            raise ConversationConflictError(
                f"Optimistic lock conflict: expected version {input_data.version}, found {state.version}"
            )

        # ── Merge updates ────────────────────────────────────────────────────
        if input_data.booking_state is not None:
            state.booking_state = input_data.booking_state
        if input_data.active_flow is not None:
            state.active_flow = input_data.active_flow
        if input_data.booking_draft is not None:
            state.booking_draft = input_data.booking_draft
        if input_data.pending_data is not None:
            state.pending_data = {**state.pending_data, **input_data.pending_data}
        if input_data.message_id is not None:
            state.message_id = input_data.message_id

        # ── Write with optimistic lock ───────────────────────────────────────
        await write_state(conn, state)

        # ── COMMIT ───────────────────────────────────────────────────────────
        await conn.execute("COMMIT")

        # ── Invalidate cache (best-effort, after commit) ─────────────────────
        await invalidate_cache(redis, input_data.chat_id)

        return ConversationUpdateResult(success=True, chat_id=input_data.chat_id)

    except Exception as e:
        with contextlib.suppress(Exception):
            await conn.execute("ROLLBACK")
        log("CONVERSATION_UPDATE_ERROR", error=str(e), chat_id=input_data.chat_id, module=MODULE)
        raise
    finally:
        await conn.close()
        await redis.aclose()


async def _main_async(
    args: object,
    redis_url: str | None = None,
    pg_url: str | None = None,
) -> dict[str, object]:
    """Windmill entrypoint."""
    if not isinstance(args, dict):
        raise RuntimeError("conversation_update failed: args is not a dict")

    try:
        input_data = ConversationUpdateInput.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"conversation_update validation error: {e}") from e

    result = await _update_conversation(input_data, redis_url, pg_url)
    return {"data": dict(result.model_dump())}


def main(
    args: object,
    redis_url: str | None = None,
    pg_url: str | None = None,
) -> dict[str, object]:
    import asyncio
    import traceback

    try:
        return asyncio.run(_main_async(args, redis_url, pg_url))
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from .._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
