from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any


def _log_flow_failure(error: dict[str, Any] | None, chat_id: str) -> None:
    step_id = str((error or {}).get("step_id", "unknown"))
    payload = json.dumps(error or {}, ensure_ascii=True, sort_keys=True)
    logging.error(f"TELEGRAM_FLOW_FAILURE step_id={step_id} chat_id={chat_id} error={payload}")


def main(
    bot_token: str,
    flow_input: dict[str, Any],
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not bot_token:
        return {"skipped": True, "reason": "empty_bot_token"}

    body = flow_input.get("body", flow_input)
    message = body.get("message", {})
    callback_query = body.get("callback_query", {})
    chat_id = str(message.get("chat", {}).get("id", "")) or str(
        callback_query.get("message", {}).get("chat", {}).get("id", "")
    )

    if not chat_id:
        return {"skipped": True, "reason": "no_chat_id"}

    step_id = (error or {}).get("step_id", "unknown")
    _log_flow_failure(error, chat_id)

    text = "Lo siento, ocurrió un error inesperado. Por favor intenta de nuevo con /start."
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        return {"sent": False, "error": str(e), "step_id": step_id}

    return {"sent": True, "chat_id": chat_id, "step_id": step_id}
