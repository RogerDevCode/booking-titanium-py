# /// script
# requires-python = ">=3.13"
# dependencies = ["redis>=7.4.0"]
# ///
from __future__ import annotations

import json
import os
from typing import Any, cast

import redis


def main(chat_id: str | None = None) -> dict[str, Any]:
    if not chat_id:
        return {"error": "chat_id requerido"}

    redis_url = os.getenv("REDIS_URL") or "redis://redis:6379"
    r = redis.from_url(redis_url)
    key = f"telegram:outbound:{chat_id}"
    data = cast("bytes", r.get(key))

    if data:
        payload = json.loads(data)
        return {"found": True, "key": key, "text": payload["text"], "timestamp": payload["timestamp"]}
    return {"found": False, "key": key}
