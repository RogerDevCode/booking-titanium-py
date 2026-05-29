# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "pydantic>=2.10.0",
#   "rapidfuzz>=3.5.2",
#   "jellyfish>=1.0.3",
#   "dateparser>=1.2.0"
# ]
# ///
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Final, Literal

import dateparser  # type: ignore[import-untyped]
import jellyfish
from pydantic import BaseModel, ConfigDict
from rapidfuzz import fuzz

from f.internal._config import DEFAULT_TIMEZONE

log = logging.getLogger("booking_titanium.datetime_resolver")

# ============================================================================
# OUTPUT MODEL
# ============================================================================


class ResolverResult(BaseModel):
    model_config = ConfigDict(strict=True)

    intent_detected: bool
    day: str | None
    datetime_iso: str | None
    confidence: float
    source: Literal["exact", "rule", "fuzzy", "phonetic", "llm", "none"]
    errors: list[str]


# ============================================================================
# DICTIONARIES
# ============================================================================

_DAYS_MAP: Final[dict[str, str]] = {
    "lunes": "lunes",
    "martes": "martes",
    "miercoles": "miercoles",
    "jueves": "jueves",
    "viernes": "viernes",
    "sabado": "sabado",
    "domingo": "domingo",
    "hoy": "today",
    "manana": "tomorrow",
    "pasado manana": "day+2",
    "proximo lunes": "next_lunes",
    "proximo martes": "next_martes",
    "proximo miercoles": "next_miercoles",
    "proximo jueves": "next_jueves",
    "proximo viernes": "next_viernes",
    "proximo sabado": "next_sabado",
    "proximo domingo": "next_domingo",
    "la semana que viene": "next_week",
    "la proxima semana": "next_week",
    "el otro lunes": "next_lunes",
    "el otro martes": "next_martes",
    "el otro miercoles": "next_miercoles",
    "el otro jueves": "next_jueves",
    "el otro viernes": "next_viernes",
    "el otro sabado": "next_sabado",
    "el otro domingo": "next_domingo",
    "dentro de un dia": "day+1",
    "dentro de dos dias": "day+2",
    "dentro de tres dias": "day+3",
    "en una semana": "day+7",
    "fin de semana": "weekend",
    "entre semana": "weekday",
}

_FALSE_COGNATES: Final[frozenset[str]] = frozenset(
    {"marzo", "mayo", "enero", "julio", "junio", "agosto", "septiembre", "noviembre", "diciembre", "febrero", "abril"}
)

_DAY_NAMES: Final[frozenset[str]] = frozenset(
    {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}
)

_ACCEPTABLE_DAYS: Final[frozenset[str]] = frozenset(
    {
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo",
        "today",
        "tomorrow",
        "day+2",
        "next_week",
        "weekend",
        "weekday",
        "next_lunes",
        "next_martes",
        "next_miercoles",
        "next_jueves",
        "next_viernes",
        "next_sabado",
        "next_domingo",
        "day+1",
        "day+3",
        "day+7",
    }
)

# ============================================================================
# NORMALIZATION
# ============================================================================


def normalize_text(text: str) -> str:
    """Normalización agresiva de texto sucio."""
    t = text.lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


# ============================================================================
# PHONETIC CACHE
# ============================================================================


@lru_cache(maxsize=512)
def _cached_metaphone(word: str) -> str:
    return jellyfish.metaphone(word)


# ============================================================================
# SCORING
# ============================================================================


def _score_token(token: str, target: str) -> tuple[float, float, float]:
    """Calcula los scores fuzzy y fonético para un token vs un target."""
    f_score = fuzz.ratio(token, target)
    t_phonetic = _cached_metaphone(token)
    tgt_phonetic = _cached_metaphone(target)
    p_score = 100.0 if t_phonetic == tgt_phonetic and len(t_phonetic) > 0 else 0.0
    exact_bonus = fuzz.partial_ratio(token, target)
    return f_score, p_score, exact_bonus


def _dynamic_threshold(token: str) -> float:
    """Threshold dinámico por longitud de palabra."""
    length = len(token)
    if length < 4:
        return 90.0
    if length < 6:
        return 85.0
    return 80.0


# ============================================================================
# SEMANTIC MATCH (MULTI-LAYER)
# ============================================================================


def semantic_match(
    normalized_text: str,
) -> tuple[str | None, float, Literal["exact", "fuzzy", "phonetic", "llm", "none"]]:
    # 1. Exact / Dictionary Match — longest phrase first
    sorted_phrases = sorted(_DAYS_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for phrase, mapped_val in sorted_phrases:
        if re.search(rf"\b{re.escape(phrase)}\b", normalized_text):
            return mapped_val, 100.0, "exact"

    # 2. Token-level matching
    tokens = normalized_text.split()
    best_score = 0.0
    best_match: str | None = None
    best_method: Literal["exact", "fuzzy", "phonetic", "llm", "none"] = "none"

    for token in tokens:
        if len(token) < 3:
            continue
        if token in _FALSE_COGNATES:
            continue

        for target, mapped_val in _DAYS_MAP.items():
            if " " in target:
                continue

            f_score, p_score, exact_bonus = _score_token(token, target)
            threshold = _dynamic_threshold(token)

            # Penalize false cognates that slip through
            if token in _FALSE_COGNATES:
                f_score *= 0.3

            total_score = (f_score * 0.5) + (p_score * 0.3) + (exact_bonus * 0.2)

            if total_score > best_score and total_score >= threshold:
                best_score = total_score
                best_match = mapped_val
                if p_score == 100.0 and f_score < 85.0:
                    best_method = "phonetic"
                else:
                    best_method = "fuzzy"

    if best_match and best_score >= 80.0:
        return best_match, best_score, best_method

    return None, best_score, "none"


# ============================================================================
# DATEPARSER (TIMEZONE-AWARE)
# ============================================================================


def parse_with_dateparser(text: str, provider_tz: str = DEFAULT_TIMEZONE) -> datetime | None:
    try:
        dt = dateparser.parse(
            text,
            languages=["es"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": provider_tz,
            },
        )
        return dt  # type: ignore[no-any-return]
    except Exception:
        return None


# ============================================================================
# LLM FALLBACK (CONTROLLED)
# ============================================================================

_LLM_DAY_PROMPT: Final[str] = (
    "Extrae el día de la semana del siguiente texto. "
    "Responde solo con una palabra válida en minúsculas y sin acentos: "
    "lunes, martes, miercoles, jueves, viernes, sabado o domingo. "
    "Si no hay ningún día, responde 'ninguno'.\n\nTexto: {input}"
)


def _llm_fallback(raw_text: str) -> str | None:
    """Fallback LLM controlado para resolución de día.

    Solo se activa cuando todos los métodos determinísticos fallan.
    Usa dateparser.parse como proxy ya que el LLM real requiere httpx async.
    En producción, el orquestador llama al LLM externo si esto retorna None.
    """
    # Intentar dateparser como último recurso determinístico antes de LLM
    dt = parse_with_dateparser(raw_text)
    if dt:
        day_name = dt.strftime("%A").lower()
        # Normalize to our internal representation
        day_map = {
            "monday": "lunes",
            "tuesday": "martes",
            "wednesday": "miercoles",
            "thursday": "jueves",
            "friday": "viernes",
            "saturday": "sabado",
            "sunday": "domingo",
            "lunes": "lunes",
            "martes": "martes",
            "miercoles": "miercoles",
            "jueves": "jueves",
            "viernes": "viernes",
            "sabado": "sabado",
            "domingo": "domingo",
        }
        return day_map.get(day_name)
    return None


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def resolve_datetime(
    raw_text: str,
    provider_tz: str = DEFAULT_TIMEZONE,
) -> ResolverResult:
    """Resuelve intención temporal con pipeline híbrido.

    Pipeline: Normalización → Tokenización → Semantic Match → Dateparser → LLM Fallback
    """
    start_time = time.monotonic()
    norm_text = normalize_text(raw_text)
    errors: list[str] = []

    # 1. Intent Detection & Semantic Resolution
    day_match, score, source = semantic_match(norm_text)
    confidence = score / 100.0

    # 2. Temporal Parsing (dateparser)
    dt: datetime | None = None
    if not day_match:
        dt = parse_with_dateparser(raw_text, provider_tz)

    # 3. LLM Fallback (solo si todo falla)
    llm_day: str | None = None
    if not day_match and not dt:
        llm_day = _llm_fallback(raw_text)
        if llm_day and llm_day in _ACCEPTABLE_DAYS:
            day_match = llm_day
            source = "llm"
            confidence = 0.75  # LLM tiene menor confianza
        else:
            errors.append("No se pudo resolver con métodos determinísticos ni LLM")

    # 4. Confidence validation
    intent_detected = bool(day_match or dt)

    if intent_detected and day_match and confidence < 0.80 and source != "llm":
        errors.append(f"Rechazado por baja confianza ({confidence:.2f})")
        intent_detected = False
        day_match = None
        source = "none"
        confidence = 0.0

    if not intent_detected:
        source = "none"
        confidence = 0.0

    # 5. Build ISO datetime
    datetime_iso: str | None = None
    if dt:
        datetime_iso = dt.isoformat()
    elif day_match and day_match in _DAY_NAMES:
        # Calculate next occurrence of this weekday
        day_index_map = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
        target_idx = day_index_map.get(day_match)
        if target_idx is not None:
            now_tz = datetime.now(UTC)
            current_idx = (now_tz.weekday()) % 7
            diff = (target_idx - current_idx + 7) % 7
            if diff == 0:
                diff = 7  # Next occurrence, not today
            target_date = now_tz + timedelta(days=diff)
            datetime_iso = target_date.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # 6. Logging estructurado
    latency_ms = int((time.monotonic() - start_time) * 1000)
    log_entry = {
        "event": "datetime_resolution",
        "input": raw_text,
        "normalized": norm_text,
        "tokens": norm_text.split(),
        "scores": {"fuzzy": score, "confidence": confidence},
        "decision": {"day": day_match, "source": source, "intent_detected": intent_detected},
        "latency_ms": latency_ms,
    }
    log.debug("datetime_resolution", extra={"resolver_log": json.dumps(log_entry, ensure_ascii=False)})

    return ResolverResult(
        intent_detected=intent_detected,
        day=day_match,
        datetime_iso=datetime_iso,
        confidence=confidence if day_match else (0.9 if dt else 0.0),
        source=source if day_match else ("rule" if dt else "none"),
        errors=errors,
    )
