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

from typing import Final, cast

from ._verify_models import ConversationVerifyInput, ConversationVerifyResult

MODULE: Final[str] = "conversation_verify"


def _coerce_input_data(input_data: ConversationVerifyInput | dict[str, object]) -> ConversationVerifyInput:
    if isinstance(input_data, ConversationVerifyInput):
        return input_data

    return ConversationVerifyInput.model_validate(input_data)


def _extract_echo_count(input_data: ConversationVerifyInput) -> int:
    persisted_state = input_data.persisted_state
    if persisted_state is None:
        raise RuntimeError("persisted_state_missing")

    if persisted_state.chat_id != input_data.expected_chat_id:
        raise RuntimeError(f"chat_id_mismatch: expected={input_data.expected_chat_id} actual={persisted_state.chat_id}")

    raw_echo_count = persisted_state.pending_data.get("echo_count")
    if not isinstance(raw_echo_count, int):
        raise RuntimeError(f"invalid_echo_count_type: {type(raw_echo_count).__name__}")

    return raw_echo_count


async def _main_async(input_data: ConversationVerifyInput) -> ConversationVerifyResult:
    actual_echo_count = _extract_echo_count(input_data)
    if actual_echo_count != input_data.expected_echo_count:
        raise RuntimeError(f"echo_count_mismatch: expected={input_data.expected_echo_count} actual={actual_echo_count}")

    return ConversationVerifyResult(
        success=True,
        verified_chat_id=input_data.expected_chat_id,
        verified_echo_count=actual_echo_count,
    )


def main(input_data: ConversationVerifyInput | dict[str, object]) -> dict[str, object]:
    import asyncio
    import traceback

    try:
        validated_input = _coerce_input_data(input_data)
        result = asyncio.run(_main_async(validated_input))
        return cast("dict[str, object]", result.model_dump())
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from .._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
