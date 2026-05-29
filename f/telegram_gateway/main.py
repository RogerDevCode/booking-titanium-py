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

import asyncio
import traceback

from pydantic import BaseModel

from ..internal._db_client import _resolve_db_url
from ..internal._wmill_adapter import get_variable
from ._gateway_logic import ClientRepository, TelegramClient
from ._gateway_models import TelegramCallback, TelegramMessage, TelegramUpdate

MODULE = "telegram_gateway"


class TelegramRouter:
    def __init__(self, telegram: TelegramClient, repository: ClientRepository) -> None:
        self.telegram = telegram
        self.repository = repository

    async def route_update(self, update: TelegramUpdate) -> str:
        if update.callback_query:
            return await self.handle_callback(update.callback_query)
        if update.message:
            return await self.handle_message(update.message)
        raise RuntimeError("unsupported_update_type")

    async def handle_callback(self, query: TelegramCallback) -> str:
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            return f"callback_handled:{data}"

        category, action = parts[0], parts[1]
        if category == "cmd":
            return f"flow_triggered:{action}"

        return f"callback_handled:{data}"

    async def handle_message(self, message: TelegramMessage) -> str:
        text = (message.text or "").strip()
        f_name = message.from_user.first_name if message.from_user else "Usuario"
        l_name = message.from_user.last_name if message.from_user else ""
        full_name = f"{f_name} {l_name}".strip()

        await self.repository.ensure_registered(full_name)

        if text == "/start":
            return "start_command"

        return "message_received"


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    try:
        update = TelegramUpdate.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"validation_error: {e}") from e

    token = str(get_variable("u/admin/TELEGRAM_BOT_TOKEN") or get_variable("TELEGRAM_BOT_TOKEN") or "")
    db_url = _resolve_db_url() or ""

    client = TelegramClient(token)
    repo = ClientRepository(db_url)
    router = TelegramRouter(client, repo)

    res = await router.route_update(update)

    chat_id: str | None = None
    text: str = ""
    callback_data: str | None = None
    username: str = "unknown"

    if update.message:
        chat_id = str(update.message.chat.id)
        text = update.message.text or ""
        username = (
            str(update.message.from_user.username)
            if update.message.from_user and update.message.from_user.username
            else "unknown"
        )
    elif update.callback_query:
        chat_id = str(update.callback_query.message.chat.id) if update.callback_query.message else None
        callback_data = update.callback_query.data
        username = (
            str(update.callback_query.from_user.username)
            if update.callback_query.from_user and update.callback_query.from_user.username
            else "unknown"
        )

    return {
        "success": True,
        "chat_id": chat_id,
        "text": text,
        "callback_data": callback_data,
        "username": username,
        "message": res,
    }


def main(args: TelegramUpdate | dict[str, object]) -> dict[str, object]:
    try:
        if isinstance(args, TelegramUpdate):
            validated = args
        else:
            validated = TelegramUpdate.model_validate(args)

        result = asyncio.run(_main_async(validated.model_dump()))

        if isinstance(result, BaseModel):
            return result.model_dump()
        return result

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            pass
        raise RuntimeError(f"Execution failed: {e}") from e
