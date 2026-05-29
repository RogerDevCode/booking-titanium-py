# /// script
# requires-python = ">=3.13"
# dependencies = ["redis>=7.4.0"]
# ///
from __future__ import annotations

import json
import os
import time
from typing import Any

import redis


def main(
    chat_id: str | None = None,
    text: str = "",
    redis_url: str | None = None,
) -> dict[str, Any]:
    if not chat_id:
        return {"intercepted": False, "reason": "no_chat_id"}

    url = os.getenv("REDIS_URL") or redis_url or "redis://localhost:6379"
    r = redis.from_url(url)
    key = f"telegram:outbound:{chat_id}"
    payload = {
        "text": str(text),
        "timestamp": time.time(),
        "captured": True,
    }
    r.setex(key, 3600, json.dumps(payload))

    return {"intercepted": True, "key": key, "text_preview": str(text)[:50]}
