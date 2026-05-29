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
#   "typing-extensions>=4.12.0",
#   "google-adk[extensions]>=2.0.0",
#   "litellm>=1.71.2"
# ]
# ///
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import traceback
from typing import Any, Final, Literal, cast

from pydantic import BaseModel

from f.nlu._tfidf_classifier import classify_intent

from .._nlu_cache import ensure_nlu_cache, get_nlu_rule
from .._wmill_adapter import log
from ._ai_agent_logic import (
    adjust_intent_with_context,
    compute_requires_fsm_routing,
    detect_context,
    detect_fsm_fast_path,
    detect_menu_command,
    detect_social,
    detect_telegram_command,
    determine_escalation_level,
    extract_entities,
    generate_ai_response,
)
from ._ai_agent_models import AIAgentInput, EntityMap, IntentResult, LLMOutput
from ._constants import INTENT
from ._gadk_agent import classify_with_gadk
from ._guardrails import sanitize_json_response, validate_input, verify_urgency
from ._llm_client import call_llm
from ._prompt_builder import build_system_prompt, build_user_message
from ._rag_context import build_rag_context

MODULE: Final[str] = "ai_agent"


async def _main_async(args: dict[str, Any]) -> dict[str, Any]:
    start_ms = int(time.time() * 1000)

    # 0. Load rules into memory cache
    await ensure_nlu_cache()

    # 0b. Resolve DB URL from args or Windmill variables
    pg_url_raw = args.get("pg_url")
    pg_url = pg_url_raw if pg_url_raw and str(pg_url_raw).strip() else os.getenv("DATABASE_URL")

    # 0c. Inject API keys from flow args into env vars for LLM client
    groq_api_key = args.get("groq_api_key")
    if groq_api_key and str(groq_api_key).strip():
        os.environ["GROQ_API_KEY"] = str(groq_api_key)

    openrouter_api_key = args.get("openrouter_api_key")
    if openrouter_api_key and str(openrouter_api_key).strip():
        os.environ["OPENROUTER_API_KEY"] = str(openrouter_api_key)

    # 1. Validate Input
    input_data = AIAgentInput.model_validate(args)
    text = input_data.text

    booking_state_name = "idle"
    if input_data.conversation_state:
        booking_state_name = input_data.conversation_state.booking_state_name

    # 2. Guardrails
    guard = validate_input(text)
    if guard["kind"] == "blocked":
        raise RuntimeError(f"guardrail_blocked: {guard['reason']}")

    # 2. Intent Detection
    intent: str = INTENT["DESCONOCIDO"]
    confidence: float = 0.0
    provider: Literal["groq", "openai", "openrouter", "fallback", "fast-path", "gadk"] = "fallback"
    cot_reasoning = "Fallback to rules-based detection"
    gadk_entities: dict[str, Any] = {}

    # 2.0 Telegram Command Fast-Path
    cmd_fast = detect_telegram_command(text)
    # 2.1 Social Fast-Path
    social = detect_social(text)
    # 2.1b Menu Fast-Path — only from idle (mid-FSM a digit is a slot/specialty pick)
    menu = detect_menu_command(text) if booking_state_name == "idle" else None
    # 2.1c FSM Fast-Path
    fsm_fast = detect_fsm_fast_path(text, input_data.conversation_state)

    if cmd_fast:
        intent, confidence = cmd_fast
        provider = "fast-path"
        cot_reasoning = "Telegram command matched"
    elif social:
        intent, confidence = social
        provider = "fast-path"
        cot_reasoning = "Social fast-path matched"
    elif menu:
        intent, confidence = menu
        provider = "fast-path"
        cot_reasoning = "Menu fast-path matched"
    elif fsm_fast:
        intent, confidence, cot_reasoning = fsm_fast
        provider = "fast-path"
    else:
        log("FAST_PATH_MISS", text=text, booking_state=booking_state_name, module=MODULE)

        # 2.2 TF-IDF Primary Check
        tfidf = classify_intent(text)
        has_enough = len(text.split()) >= 2

        if tfidf["confidence"] >= 0.85 and has_enough:
            intent = str(tfidf["intent"])
            confidence = float(tfidf["confidence"])
            cot_reasoning = f"TF-IDF semantic match ({intent})"
            log("TF-IDF bypass GADK", intent=intent, confidence=confidence, module=MODULE)
        else:
            # 2.3 GADK Fallback — single call to Gemini via ADK with tool calling
            gadk_start = int(time.time() * 1000)
            gadk_result = await classify_with_gadk(text, input_data.chat_id)
            gadk_latency = int(time.time() * 1000) - gadk_start

            if gadk_result and gadk_result.get("intent") != INTENT["DESCONOCIDO"]:
                intent = gadk_result["intent"]
                confidence = gadk_result["confidence"]
                gadk_entities = gadk_result.get("entities", {})
                provider = "gadk"
                cot_reasoning = f"GADK classification (latency={gadk_latency}ms)"
                log("GADK classification", intent=intent, confidence=confidence, latency_ms=gadk_latency)
            else:
                log("GADK failed or unknown, falling back to TF-IDF", latency_ms=gadk_latency)
                if tfidf["confidence"] >= float(get_nlu_rule("escalation_tfidf_minimum", 0.4)) and has_enough:
                    intent = str(tfidf["intent"])
                    confidence = float(tfidf["confidence"])
                    cot_reasoning = f"TF-IDF semantic match ({intent})"

                # 2.4 LLM Path (only if TF-IDF confidence is low or unknown)
                rag_context = None
                tfidf_confident = confidence >= 0.9
                if not tfidf_confident and intent in [INTENT["PREGUNTA_GENERAL"], INTENT["DESCONOCIDO"]]:
                    try:
                        rag_res = await build_rag_context(
                            input_data.provider_id, text, pg_url=str(pg_url) if pg_url else None
                        )
                        rag_context = rag_res["context"]
                    except Exception as e:
                        log("RAG_CONTEXT_FAILED", error=str(e), chat_id=input_data.chat_id, module=MODULE)
                        rag_context = None

                    sys_prompt = build_system_prompt(rag_context)
                    user_msg = build_user_message(text)

                    err_llm, llm_res = await call_llm(sys_prompt, user_msg)
                    if not err_llm and llm_res:
                        try:
                            cleaned = sanitize_json_response(llm_res.content)
                            raw_json = json.loads(cleaned)
                            llm_out = LLMOutput.model_validate(raw_json)
                            intent = llm_out.intent
                            confidence = llm_out.confidence
                            provider = llm_res.provider
                            cot_reasoning = "LLM classification (fallback)"
                        except Exception as e:
                            log("LLM response parse failed", error=str(e), content=llm_res.content)

    # 2.5 Context Adjustment
    adj = adjust_intent_with_context(text, intent, confidence, input_data.conversation_state)
    if adj["adjusted"]:
        intent = str(adj["intent"])
        confidence = cast("float", adj["confidence"])
        cot_reasoning = str(adj["reason"])

    # 3. Entities & Context Logic
    regex_entities = extract_entities(text)
    # Merge GADK entities (higher priority) with regex entities (fallback)
    merged_entities_data = {
        "date": gadk_entities.get("fecha") or regex_entities.date,
        "time": gadk_entities.get("hora") or regex_entities.time,
        "provider_name": gadk_entities.get("doctor") or regex_entities.provider_name,
        "provider_id": regex_entities.provider_id,
        "service_type": gadk_entities.get("especialidad") or regex_entities.service_type,
        "service_id": regex_entities.service_id,
        "booking_id": gadk_entities.get("booking_id") or regex_entities.booking_id,
        "channel": regex_entities.channel,
        "reminder_window": regex_entities.reminder_window,
    }
    entities = EntityMap(**merged_entities_data)
    ctx = detect_context(text, entities)

    ai_resp, needs_more, follow_up = generate_ai_response(intent, entities, ctx, input_data.user_profile)

    esc_level = determine_escalation_level(intent, text, confidence)

    result = IntentResult(
        intent=intent,
        confidence=confidence,
        entities=entities,
        context=ctx,
        subtype=None,
        ai_response=ai_resp,
        needs_more_info=needs_more,
        follow_up=follow_up,
        requires_human=(esc_level != "none"),
        escalation_level=esc_level,
        cot_reasoning=cot_reasoning,
        validation_passed=True,
    )

    verified = verify_urgency(result, text)

    # Compute requires_fsm_routing based on intent, booking state, and confidence
    requires_fsm = compute_requires_fsm_routing(verified.intent, booking_state_name, confidence)

    final_result = IntentResult.model_validate({**verified.model_dump(), "requires_fsm_routing": requires_fsm})

    # Log/Trace performance (simplified)
    log(
        "AI Agent execution complete",
        intent=final_result.intent,
        confidence=final_result.confidence,
        provider=provider,
        latency_ms=int(time.time() * 1000) - start_ms,
    )

    return {"success": True, "data": final_result.model_dump(), "error_message": None}


def main(
    chat_id: str,
    text: str,
    provider_id: str | None = None,
    conversation_state: dict[str, Any] | None = None,
    pg_url: str | None = None,
    groq_api_key: str | None = None,
    openrouter_api_key: str | None = None,
) -> dict[str, object]:
    args: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "provider_id": provider_id,
        "conversation_state": conversation_state,
        "pg_url": pg_url,
        "groq_api_key": groq_api_key,
        "openrouter_api_key": openrouter_api_key,
    }

    try:
        result = asyncio.run(_main_async(args))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        with contextlib.suppress(Exception):
            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)

        raise RuntimeError(f"Execution failed: {e}") from e
