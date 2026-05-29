from __future__ import annotations

import json
from typing import cast

from ._db_client import create_db_client
from ._redis_client import create_redis_client

# Global memory cache (fallback for fast sync access if needed)
_NLU_CACHE: dict[str, object] = {}


async def load_nlu_rules_to_redis() -> None:
    """Loads NLU rules from Postgres to Redis."""
    db = await create_db_client()
    try:
        rows = await db.fetch("SELECT rule_key, threshold_value, keywords FROM nlu_rules")
        redis_client = await create_redis_client()
        try:
            # Delete old rules to ensure clean sync
            await redis_client.delete("booking:nlu_rules")
            rules_to_set: dict[str, str] = {}
            for row in rows:
                key = str(row["rule_key"])
                keywords = row.get("keywords")
                threshold_value = row.get("threshold_value")
                if keywords is not None:
                    if isinstance(keywords, str):
                        rules_to_set[key] = keywords
                    else:
                        rules_to_set[key] = json.dumps(keywords)
                elif threshold_value is not None:
                    rules_to_set[key] = str(threshold_value)

            if rules_to_set:
                await redis_client.hset("booking:nlu_rules", mapping=rules_to_set)  # type: ignore[misc]
        finally:
            await redis_client.aclose()
    finally:
        await db.close()


_DEFAULT_NLU_RULES: dict[str, object] = {
    "msg_main_menu": "🏥 *AutoAgenda - Menú Principal*\n\n¿Cómo podemos ayudarte hoy?",
    "msg_slot_taken": "Ese horario ya fue reservado.",
    "msg_no_service": "No hay servicios.",
    "msg_generic": ("No pudimos confirmar tu hora en este momento. Por favor intenta de nuevo en unos minutos."),
    "intent_keywords_saludo": ["hola", "buenas"],
    "intent_keywords_urgencia": ["urgencia", "emergencia"],
    "urgencia": ["urgencia"],
    "urgency_words": ["urgencia", "emergencia", "rapido"],
    "greetings": ["hola", "buenas", "saludos"],
    "greeting_phrases": ["buenos dias", "buen dia"],
    "farewells": ["adios", "chao"],
    "farewell_phrases": ["hasta luego", "nos vemos"],
    "confidence_bound_high_min": 0.85,
    "escalation_medical_emergency_min": 0.8,
    "escalation_priority_queue_max": 0.6,
    "escalation_human_handoff_max": 0.4,
    "escalation_tfidf_minimum": 0.4,
    "day_names": {
        "lunes": "Lunes",
        "martes": "Martes",
        "miercoles": "Miércoles",
        "jueves": "Jueves",
        "viernes": "Viernes",
        "sabado": "Sábado",
        "domingo": "Domingo",
    },
    "relative_dates": ["hoy", "mañana", "manana"],
}


async def ensure_nlu_cache() -> None:
    """Ensures the global memory cache is populated."""
    if _NLU_CACHE:
        return

    # Seed with default fallback values
    _NLU_CACHE.clear()
    _NLU_CACHE.update(_DEFAULT_NLU_RULES)

    try:
        # Try loading from Redis first
        redis_client = await create_redis_client()
        try:
            rules = cast("dict[str, str]", await redis_client.hgetall("booking:nlu_rules"))  # type: ignore[misc]

            if not rules:
                # Load from DB to Redis
                await load_nlu_rules_to_redis()
                rules = cast("dict[str, str]", await redis_client.hgetall("booking:nlu_rules"))  # type: ignore[misc]

            if not rules:
                return

            for key_name, v in rules.items():
                if not v:
                    continue
                try:
                    _NLU_CACHE[key_name] = json.loads(v)
                except json.JSONDecodeError:
                    try:
                        _NLU_CACHE[key_name] = float(v)
                    except ValueError:
                        _NLU_CACHE[key_name] = v
        finally:
            await redis_client.aclose()
    except Exception:
        # Fallback to defaults already loaded in cache
        pass


def get_nlu_rule[T](rule_key: str, default: T) -> T:
    """Gets an NLU rule from the memory cache synchronously."""
    return cast("T", _NLU_CACHE.get(rule_key, default))
