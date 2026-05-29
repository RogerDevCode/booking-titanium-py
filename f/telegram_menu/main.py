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

import traceback

from ._menu_logic import MenuController
from ._menu_models import MenuInput

MODULE = "telegram_menu"


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    input_data = MenuInput(
        action=str(args.get("action", "show")),
        chat_id=str(args.get("chat_id", "")),
        user_input=str(args.get("user_input")) if args.get("user_input") else None,
    )

    controller = MenuController()
    response = await controller.handle(input_data)

    return {
        "success": True,
        "handled": response.handled,
        "response_text": response.response_text,
        "inline_buttons": response.inline_buttons,
    }


def main(action: str, chat_id: str, user_input: str | None = None) -> dict[str, object]:
    import asyncio

    args: dict[str, object] = {"action": action, "chat_id": chat_id, "user_input": user_input}
    try:
        return asyncio.run(_main_async(args))
    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_MENU_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            print(f"CRITICAL ERROR: {e}\n{tb}")
        raise RuntimeError(f"Menu failed: {e}") from e
