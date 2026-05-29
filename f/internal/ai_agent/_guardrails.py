import re
from typing import Literal, TypedDict

from .._nlu_cache import get_nlu_rule
from ._ai_agent_models import IntentResult
from ._constants import INTENT


class GuardrailPass(TypedDict):
    kind: Literal["pass"]


class GuardrailBlocked(TypedDict):
    kind: Literal["blocked"]
    reason: str
    category: Literal["injection", "unicode", "length", "leakage"]


GuardrailResult = GuardrailPass | GuardrailBlocked

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"developer\s+mode",
    r"reveal\s+(the\s+)?system\s+prompt",
    r"disregard\s+instructions?",
    r"you\s+are\s+now",
    r"pretend\s+to\s+be",
    r"forget\s+(all|your|the)\s+(instructions|rules|prompt)",
]

DANGEROUS_UNICODE = ["\u200b", "\u200e", "\u200f", "\u202a", "\u202b", "\u202d", "\u202e", "\ufeff"]

LEAKAGE_PATTERNS = [
    "SYSTEM_INSTRUCTIONS",
    "UNTRUSTED INPUT",
    "BEGIN USER DATA",
    "END USER DATA",
    "INTENT DEFINITIONS",
    "REGLAS DE DESEMPATE",
]


def validate_input(text: str) -> GuardrailResult:
    trimmed = text.strip()
    if not trimmed:
        return {"kind": "blocked", "reason": "Empty input", "category": "length"}
    if len(trimmed) > 500:
        return {"kind": "blocked", "reason": "Input too long (max 500 chars)", "category": "length"}

    for p in INJECTION_PATTERNS:
        if re.search(p, trimmed, re.IGNORECASE):
            return {"kind": "blocked", "reason": "Potential prompt injection detected", "category": "injection"}

    for char in DANGEROUS_UNICODE:
        if char in trimmed:
            return {"kind": "blocked", "reason": "Dangerous unicode character detected", "category": "unicode"}

    return {"kind": "pass"}


def validate_output(content: str) -> GuardrailResult:
    trimmed = content.strip()
    if not trimmed:
        return {"kind": "blocked", "reason": "Empty LLM response", "category": "length"}
    if len(trimmed) > 4000:
        return {"kind": "blocked", "reason": "LLM response too long", "category": "length"}

    for p in LEAKAGE_PATTERNS:
        if p in trimmed:
            return {"kind": "blocked", "reason": "System prompt leakage detected", "category": "leakage"}

    return {"kind": "pass"}


def sanitize_json_response(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()

    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first != -1 and last != -1 and last > first:
        return cleaned[first : last + 1]
    return cleaned


def verify_urgency(result: IntentResult, text: str) -> IntentResult:
    lower = text.lower().strip()
    # Simple normalization for urgency check
    accents = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}
    for k, v in accents.items():
        lower = lower.replace(k, v)

    urgency_words: list[str] = get_nlu_rule("urgency_words", [])
    has_urgency = any(w in lower for w in urgency_words)
    has_typos = any(x in lower for x in ["urjente", "urgnete", "urjencia", "nececito atencion", "duele"])

    if result.intent == INTENT["URGENCIA"]:
        if not has_urgency and not has_typos:
            result.confidence = min(result.confidence, 0.4)
            result.validation_passed = False
            result.validation_errors.append("Urgency intent detected but no urgency words found in text")
        elif result.confidence < 0.7:
            result.confidence = 0.75

    if result.intent != INTENT["URGENCIA"] and (has_urgency or has_typos) and result.confidence < 0.5:
        result.intent = INTENT["URGENCIA"]
        result.confidence = 0.75
        result.validation_errors.append("Upgraded to urgent care based on urgency keywords")

    return result
