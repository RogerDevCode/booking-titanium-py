from __future__ import annotations

import os
import time
from typing import Any, Final, Literal, TypedDict, cast

import httpx
from pydantic import BaseModel, ConfigDict

from .._wmill_adapter import get_variable, log

# ============================================================================
# LLM CLIENT — Configurable Provider Chain (v6.0)
# ============================================================================

type LLMProvider = Literal["groq", "openai", "openrouter"]


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ProviderConfig(TypedDict):
    name: LLMProvider
    url: str
    key: str | None
    model: str
    structured: bool


class LLMResponse(BaseModel):
    model_config = ConfigDict(strict=True)
    content: str
    provider: LLMProvider
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cached: bool = False


async def call_llm(system_prompt: str, user_message: str) -> tuple[Exception | None, LLMResponse | None]:
    # ─── Configuration ──────────────
    order_str = (
        get_variable("u/admin/LLM_PROVIDER_ORDER") or os.getenv("LLM_PROVIDER_ORDER") or "groq,openai,openrouter"
    )
    provider_order = [s.strip().lower() for s in order_str.split(",")]

    providers: Final[dict[str, ProviderConfig]] = {
        "groq": {
            "name": "groq",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "key": get_variable("u/admin/GROQ_API_KEY") or os.getenv("GROQ_API_KEY"),
            "model": get_variable("u/admin/GROQ_MODEL") or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile",
            "structured": False,
        },
        "openai": {
            "name": "openai",
            "url": "https://api.openai.com/v1/chat/completions",
            "key": get_variable("u/admin/OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
            "model": get_variable("u/admin/OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
            "structured": True,
        },
        "openrouter": {
            "name": "openrouter",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "key": get_variable("u/admin/OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY"),
            "model": (
                get_variable("u/admin/OPENROUTER_MODEL") or os.getenv("OPENROUTER_MODEL") or "openrouter/auto:free"
            ),
            "structured": False,
        },
    }

    messages: list[ChatMessage] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for p_key in provider_order:
        p = providers.get(p_key)
        if not p or not p["key"]:
            continue

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers = {"Authorization": f"Bearer {p['key']}", "Content-Type": "application/json"}

                # Attributions for OpenRouter
                if p["name"] == "openrouter":
                    headers["HTTP-Referer"] = "https://localhost"
                    headers["X-Title"] = "Windmill Medical Booking"

                body: dict[str, object] = {
                    "model": p["model"],
                    "messages": cast("list[object]", messages),
                    "temperature": 0.0,
                    "max_tokens": 512,
                }

                # Structured Output for OpenAI
                if p["structured"]:
                    body["response_format"] = {"type": "json_object"}

                response = await client.post(p["url"], headers=headers, json=body)

                if response.status_code != 200:
                    log(f"LLM Provider {p_key} failed", status=response.status_code, body=response.text)
                    continue

                data = cast("dict[str, Any]", response.json())  # httpx.json returns Any
                content = str(data["choices"][0]["message"]["content"])
                usage = cast("dict[str, int]", data.get("usage", {}))

                return None, LLMResponse(
                    content=content,
                    provider=p["name"],
                    tokens_in=usage.get("prompt_tokens", 0),
                    tokens_out=usage.get("completion_tokens", 0),
                    latency_ms=int((time.time() - start_time) * 1000),
                )

        except Exception as e:
            log(f"LLM call to {p_key} exception", error=str(e))
            continue

    return Exception("All LLM providers failed"), None


# To satisfy the data mapping in response.json()
