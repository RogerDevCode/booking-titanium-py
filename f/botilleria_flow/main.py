from __future__ import annotations

# NOTE: This file was a Windmill workflow orchestrator (task_script/workflow decorators).
# Windmill has been removed from the project. This file is kept for reference only.
# The equivalent logic now runs inside f/telegram_gateway/worker.py via arq.


async def main(
    update_id: int,
    message_chat_id: int,
    message_text: str | None = None,
    message_from_id: int | None = None,
    message_from_username: str | None = None,
    bot_token: str = "",
) -> dict[str, object]:
    """
    Placeholder — was a Windmill flow.
    Real flow: Telegram Webhook → arq worker → fsm_router → telegram_send
    """
    raise NotImplementedError("botilleria_flow: use the arq worker pipeline instead")
