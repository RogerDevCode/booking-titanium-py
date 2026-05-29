from __future__ import annotations

import math
import re
import unicodedata
from typing import Final, TypedDict

from ._constants import DAY_NAMES, INTENT, INTENT_KEYWORDS, RELATIVE_DATES, RULE_CONFIDENCE_VALUES

"""
PRE-FLIGHT
Mission          : TF-IDF + Cosine Similarity intent classifier.
DB Tables        : NONE
Concurrency Risk : NO
GCal Calls      : NO
Idempotency Key  : NO
RLS Tenant ID   : NO
Zod Schemas      : NO
"""

# REFERENCE CORPUS — Real-world examples per intent.
# All examples represent post-preprocessor text (modisms, typos, and slang
# already normalized by f/message_preprocessor before reaching NLU).
CORPUS: Final[dict[str, list[str]]] = {
    INTENT["CREAR_CITA"]: [
        "quiero agendar una hora para mañana",
        "necesito hora con el doctor el lunes",
        "quiero una hora para el viernes a las diez",
        "reservar turno con especialista",
        "agendar consulta medica urgente",
        "necesito hora urgente",
        "solicitar hora para control",
        "quiero una hora",
        "quiero de inmediato una hora",
        "hola quiero agendar para mañana a las 10",
        "necesito agendar una hora lo antes posible",
        "quiero hacer una hora para esta semana",
        "puedo hacer una hora para el jueves",
        "quiero agendar una cita para mañana",
        "necesito cita urgente",
        "quiero hacer una cita para esta semana",
    ],
    INTENT["CANCELAR_CITA"]: [
        "quiero cancelar mi hora del martes",
        "no podre ir cancélame la hora",
        "anular turno programado para mañana",
        "eliminar hora agendada",
        "borrar mi reserva del jueves",
        "no podre ir cancélame",
        "cancelar hora que tengo",
        "necesito cancelar mi hora de mañana",
        "cancelar hora del lunes por favor",
        "necesito cancelar mi hora",
        "quiero cancelar mi hora",
        "cancela mi hora",
        "quiero anular mi hora",
        "quiero cancelar mi cita del martes",
        "necesito cancelar mi cita",
        "cancelar cita que tengo",
    ],
    INTENT["REAGENDAR_CITA"]: [
        "necesito cambiar mi cita del viernes al jueves",
        "reprogramar turno para la otra semana",
        "mejor para el miércoles a las once",
        "mover mi hora de mañana para pasado",
        "quiero cambiar la cita para otro dia",
        "reagendar cita para la próxima semana",
        "cambiar cita para el lunes",
        "necesito reagendar mi consulta",
    ],
    INTENT["VER_DISPONIBILIDAD"]: [
        "tienen disponibilidad para el lunes",
        "esta libre el doctor el martes por la mañana",
        "hay hueco para hoy a las tres",
        "tiene hora disponible esta semana",
        "puedo agendar para mañana",
        "tiene libre el lunes",
        "hay disponibilidad para esta semana",
        "cuando tienen hora disponible",
        "que horas tienen para el viernes",
    ],
    INTENT["VER_MIS_CITAS"]: [
        "tengo alguna hora agendada",
        "cuando es mi hora",
        "mis horas próximas",
        "confirmame el turno que reserve",
        "quiero saber si tengo hora",
        "tengo hora para mañana",
        "revisar mis reservas",
        "ver mis horas",
        "que horas tengo",
        "mis citas próximas",
        "tengo alguna cita agendada",
        "ver mis citas",
    ],
    INTENT["SALUDO"]: [
        "hola buenos dias",
        "buenas tardes doctor",
        "hola como esta",
        "saludos necesito ayuda",
        "buenas noches",
        "hola",
        "buenas",
    ],
    INTENT["DESPEDIDA"]: [
        "chau gracias",
        "adios que tenga buen dia",
        "hasta luego",
        "nos vemos gracias por todo",
        "chao",
        "hasta pronto",
    ],
    INTENT["AGRADECIMIENTO"]: [
        "muchas gracias",
        "gracias por favor",
        "te agradezco mucho",
        "gracias doctor",
        "mil gracias",
        "muy amable gracias",
    ],
    INTENT["URGENCIA"]: [
        "necesito atención urgente",
        "es una emergencia",
        "urgente por favor inmediatamente",
        "necesito ayuda urgente de inmediato",
        "tengo urgencia médica",
        "es urgente necesito doctor",
        "inmediatamente necesito atención",
        "mi hijo tiene fiebre muy alta urgente",
        "dolor muy fuerte necesito médico ya",
    ],
}

STOP_WORDS: Final[set[str]] = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "al",
    "para",
    "por",
    "con",
    "sin",
    "sobre",
    "es",
    "son",
    "esta",
    "estan",
    "fue",
    "ser",
    "hay",
    "que",
    "se",
    "no",
    "me",
    "te",
    "le",
    "les",
    "lo",
    "mi",
    "tu",
    "su",
    "nuestro",
    "sus",
    "y",
    "o",
    "pero",
    "si",
    "como",
    "donde",
    "cuando",
    "muy",
    "mas",
    "menos",
    "bien",
    "asi",
}

# Solo entradas que el preprocessor NO cubre (residuales post-pipeline).
# Las entradas idempotentes y las que ya maneja el preprocessor fueron eliminadas.
TYPO_MAP: Final[dict[str, str]] = {
    "libre": "disponible",
    "configuro": "configurar",
    # Sinónimos médicos chilenos
    "hora": "cita",
    "horas": "citas",
}


def _keyword_match(tokens: list[str]) -> tuple[str, float] | None:
    """Pre-TF-IDF: retorna intent si hay match exacto de keyword en tokens."""
    token_set = set(tokens)
    priority_order = [
        INTENT["URGENCIA"],
        INTENT["SALUDO"],
        INTENT["DESPEDIDA"],
        INTENT["AGRADECIMIENTO"],
        INTENT["CREAR_CITA"],
        INTENT["CANCELAR_CITA"],
        INTENT["REAGENDAR_CITA"],
        INTENT["VER_MIS_CITAS"],
        INTENT["VER_MIS_DATOS"],
        INTENT["VER_DISPONIBILIDAD"],
    ]
    kw_map: dict[str, list[str]] = INTENT_KEYWORDS
    for intent in priority_order:
        keywords = kw_map.get(intent, [])
        for kw in keywords:
            kw_tokens = kw.lower().split()
            if all(t in token_set for t in kw_tokens):
                confidence_key = f"{intent}_exact" if len(kw_tokens) == 1 else f"{intent}_phrase"
                confidence = RULE_CONFIDENCE_VALUES.get(
                    confidence_key,
                    RULE_CONFIDENCE_VALUES.get("greeting_exact", 0.9),
                )
                return intent, confidence
    return None


def deterministic_layer_0(text: str) -> tuple[str, float] | None:
    """Capa 0: Mapeo exacto determinista para short-texts y dígitos, evitando fallos de TF-IDF."""
    lower = text.strip().lower()
    mapping: dict[str, str] = {
        "1": INTENT["CREAR_CITA"],
        "agendar": INTENT["CREAR_CITA"],
        "2": INTENT["VER_MIS_CITAS"],
        "mis citas": INTENT["VER_MIS_CITAS"],
        "reporte": INTENT["GENERAR_REPORTE"],
        "informe": INTENT["GENERAR_REPORTE"],
        "3": INTENT["ACTIVAR_RECORDATORIOS"],
        "recordatorios": INTENT["ACTIVAR_RECORDATORIOS"],
        "4": INTENT["PREGUNTA_GENERAL"],
        "info": INTENT["PREGUNTA_GENERAL"],
        "5": INTENT["VER_MIS_DATOS"],
        "perfil": INTENT["VER_MIS_DATOS"],
        "sí": INTENT["CREAR_CITA"],  # default confirm
        "si": INTENT["CREAR_CITA"],
        "y": INTENT["CREAR_CITA"],
        "no": INTENT["CANCELAR_CITA"],  # default reject
        "cancelar": INTENT["CANCELAR_CITA"],
    }
    if lower in mapping:
        return mapping[lower], 0.95
    return None


def _normalize(text: str) -> list[str]:
    """Light normalization handles Chilean slang and common typos."""
    text = text.lower().strip()
    # Normalize unicode (accents)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    # Remove punctuation
    text = re.sub(r"[?¿!¡.,;:()]", " ", text)
    tokens = text.split()

    result: list[str] = []
    for w in tokens:
        mapped = TYPO_MAP.get(w, w)
        if len(mapped) > 1 and mapped not in STOP_WORDS:
            result.append(mapped)
    return result


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0

    length = len(tokens) or 1
    for t in tf:
        tf[t] = tf[t] / length
    return tf


def _compute_idf(documents: list[list[str]]) -> dict[str, float]:
    idf: dict[str, float] = {}
    n = len(documents)
    for doc in documents:
        seen = set(doc)
        for t in seen:
            idf[t] = idf.get(t, 0.0) + 1.0

    for t in idf:
        idf[t] = math.log(n / (1.0 + idf[t]))
    return idf


def _cosine_similarity(a: dict[str, float], b: dict[str, float], idf: dict[str, float]) -> float:
    all_terms = set(a.keys()) | set(b.keys())
    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0

    for t in all_terms:
        w_a = a.get(t, 0.0) * idf.get(t, 0.0)
        w_b = b.get(t, 0.0) * idf.get(t, 0.0)
        dot += w_a * w_b
        mag_a += w_a * w_a
        mag_b += w_b * w_b

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (math.sqrt(mag_a) * math.sqrt(mag_b))


class ModelData(TypedDict):
    idf: dict[str, float]
    intents: list[str]
    corpus: dict[str, list[list[str]]]


# Model singleton
_model_cache: ModelData | None = None


def _get_model() -> ModelData:
    global _model_cache
    if _model_cache is None:
        intents = list(CORPUS.keys())
        intent_docs_arr = [_normalize(doc) for intent in intents for doc in CORPUS[intent]]

        idf = _compute_idf(intent_docs_arr)
        _model_cache = {
            "idf": idf,
            "intents": intents,
            "corpus": {intent: [_normalize(d) for d in docs] for intent, docs in CORPUS.items()},
        }
    return _model_cache


class ScoreEntry(TypedDict):
    intent: str
    score: float


class TfIdfResult(TypedDict):
    intent: str
    confidence: float
    scores: list[ScoreEntry]


def extract_entities(text: str) -> dict[str, str]:
    """Extract date/time entities from normalized text.

    Returns dict with any subset of: day, relative_date, time.
    All values are strings — compatible with OrchestratorInput.entities.
    Does NOT query DB — only pattern/keyword matching on text.
    """
    entities: dict[str, str] = {}
    text_lower = text.lower()
    tokens = set(text_lower.split())

    # Day of week (uses stripped/unaccented form for matching)
    for day_key, day_display in DAY_NAMES.items():
        if day_key in tokens:
            entities["day"] = day_display
            break

    # Relative date (hoy, mañana, manana)
    for rel in RELATIVE_DATES:
        rel_norm = rel.replace("ñ", "n")
        if rel in tokens or rel_norm in tokens:
            entities["relative_date"] = rel
            break

    # Time: "a las HH" or "a las HH:MM"
    time_match = re.search(r"a las (\d{1,2})(?::(\d{2}))?", text_lower)
    if time_match:
        hour = time_match.group(1).zfill(2)
        minute = time_match.group(2) or "00"
        entities["time"] = f"{hour}:{minute}"

    return entities


def classify_intent(text: str) -> TfIdfResult:
    """Classifies intent. Keyword match first, TF-IDF as fallback."""
    # Layer 0: deterministic match (fastest, prevents dropping short texts)
    l0_result = deterministic_layer_0(text)
    if l0_result is not None:
        l0_intent, l0_confidence = l0_result
        return {
            "intent": l0_intent,
            "confidence": l0_confidence,
            "scores": [{"intent": l0_intent, "score": l0_confidence}],
        }

    model = _get_model()
    query_tokens = _normalize(text)

    if not query_tokens:
        return {"intent": INTENT["DESCONOCIDO"], "confidence": 0.0, "scores": []}

    # Layer 1: keyword match (fast, deterministic)
    kw_result = _keyword_match(query_tokens)
    if kw_result is not None:
        kw_intent, kw_confidence = kw_result
        return {
            "intent": kw_intent,
            "confidence": kw_confidence,
            "scores": [{"intent": kw_intent, "score": kw_confidence}],
        }

    # Layer 2: TF-IDF cosine similarity
    query_tf = _compute_tf(query_tokens)
    scores: list[ScoreEntry] = []

    for intent in model["intents"]:
        max_score = 0.0
        # Compare against each document in the corpus for this intent
        for doc_tokens in model["corpus"][intent]:
            doc_tf = _compute_tf(doc_tokens)
            sim = _cosine_similarity(query_tf, doc_tf, model["idf"])
            if sim > max_score:
                max_score = sim

        scores.append({"intent": intent, "score": max_score})

    # Sort descending
    scores.sort(key=lambda x: x["score"], reverse=True)

    # Normalize confidence
    top_score = scores[0]["score"] if scores else 0.0
    second_score = scores[1]["score"] if len(scores) > 1 else 0.0
    gap = top_score - second_score
    if top_score == 0.0:
        confidence = 0.0
    else:
        confidence = min(0.5 + gap * 3.0 + top_score * 2.0, 0.95)

    return {
        "intent": scores[0]["intent"] if scores else INTENT["DESCONOCIDO"],
        "confidence": confidence,
        "scores": scores[:3],
    }
