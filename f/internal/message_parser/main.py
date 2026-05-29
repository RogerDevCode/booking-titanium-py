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

from pydantic import BaseModel, ConfigDict


class ParserInput(BaseModel):
    model_config = ConfigDict(strict=True)
    text: str
    chat_id: str


class ParserResult(BaseModel):
    model_config = ConfigDict(strict=True)
    success: bool
    data: dict[str, object]


async def _main_async(args: dict[str, object]) -> dict[str, object]:
    try:
        input_data = ParserInput.model_validate(args)
    except Exception as e:
        raise RuntimeError(f"validation_error: {e}") from e

    # Basic parser implementation
    return {
        "success": True,
        "data": {"text": input_data.text, "chat_id": input_data.chat_id, "is_command": input_data.text.startswith("/")},
    }


def main(args: dict[str, object]) -> dict[str, object]:
    return asyncio.run(_main_async(args))
