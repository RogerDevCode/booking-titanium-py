from __future__ import annotations

import math
import re
import unicodedata
from typing import Final, TypedDict

INTENT_CREAR_CITA = "crear_cita"
INTENT_CANCELAR_CITA = "cancelar_cita"
INTENT_REAGENDAR_CITA = "reagendar_cita"
INTENT_VER_DISPONIBILIDAD = "ver_disponibilidad"
INTENT_VER_MIS_CITAS = "mis_citas"
INTENT_CONSULTAR_CITA = "consultar_cita"
INTENT_DESCONOCIDO = "desconocido"
INTENT_SALUDO = "saludo"
INTENT_DESPEDIDA = "despedida"

CORPUS: Final[dict[str, list[str]]] = {
    INTENT_CREAR_CITA: [
        "quiero agendar una cita para mañana",
        "necesito hora con el doctor el lunes",
        "reservar turno con especialista",
        "agendar consulta medica urgente",
        "necesito cita urgente",
        "pedir hora para control",
        "kiero una ora",
        "hola quiero agendar para manana a las 10",
    ],
    INTENT_CANCELAR_CITA: [
        "quiero cancelar mi cita",
        "no podre ir kanselame la hora",
        "anular turno programado",
        "eliminar cita agendada",
        "borrar mi reserva",
        "cancelar la hora",
    ],
    INTENT_REAGENDAR_CITA: [
        "necesito cambiar mi cita",
        "reprogramar turno",
        "mover mi hora",
        "kiero kambiar la cita",
    ],
    INTENT_VER_DISPONIBILIDAD: [
        "tienen disponibilidad",
        "esta libre el doctor",
        "hay hueco para hoy",
        "tiene ora disponible",
        "puedo agendar",
        "hay hora",
    ],
    INTENT_VER_MIS_CITAS: [
        "tengo alguna cita agendada",
        "cuando es mi hora",
        "mis citas",
        "confirmame el turno",
        "quiero saber si tengo hora",
        "revisar mis reservas",
    ],
    INTENT_CONSULTAR_CITA: [
        "como esta mi cita",
        "cual es el estado de mi reserva",
        "ver detalle de mi cita",
        "consultar mi turno",
        "informacion de mi cita",
        "quiero saber el detalle de mi hora",
        "estado de mi cita",
    ],
    INTENT_SALUDO: [
        "hola buenos dias",
        "buenas tardes doctor",
        "ola como esta",
        "saludos",
        "buenas noches",
    ],
    INTENT_DESPEDIDA: [
        "chau gracias",
        "adios",
        "hasta luego",
        "nos vemos",
        "chao",
    ],
}

STOP_WORDS: Final[set[str]] = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
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
    "necesito",
    "quiero",
    "puedo",
    "debo",
}

TYPO_MAP: Final[dict[str, str]] = {
    "kiero": "quiero",
    "ora": "hora",
    "kansela": "cancela",
    "reprograma": "reprograma",
    "kambiar": "cambiar",
    "sita": "cita",
    "truno": "turno",
    "agendar": "agendar",
    "manana": "mañana",
    "libre": "disponible",
}


def _normalize(text: str) -> list[str]:
    text = text.lower().strip()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    text = re.sub(r"[?¿!¡.,;:()]", " ", text)
    result: list[str] = []
    for w in text.split():
        mapped = TYPO_MAP.get(w, w)
        if len(mapped) > 1 and mapped not in STOP_WORDS:
            result.append(mapped)
    return result


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0
    length = len(tokens) or 1
    return {t: v / length for t, v in tf.items()}


def _compute_idf(docs: list[list[str]]) -> dict[str, float]:
    idf: dict[str, float] = {}
    n = len(docs)
    for doc in docs:
        for t in set(doc):
            idf[t] = idf.get(t, 0.0) + 1.0
    return {t: math.log(n / (1.0 + v)) for t, v in idf.items()}


def _cosine_similarity(a: dict[str, float], b: dict[str, float], idf: dict[str, float]) -> float:
    dot = mag_a = mag_b = 0.0
    for t in set(a) | set(b):
        wa, wb = a.get(t, 0.0) * idf.get(t, 0.0), b.get(t, 0.0) * idf.get(t, 0.0)
        dot += wa * wb
        mag_a += wa * wa
        mag_b += wb * wb
    return dot / (math.sqrt(mag_a) * math.sqrt(mag_b)) if mag_a and mag_b else 0.0


class ModelData(TypedDict):
    idf: dict[str, float]
    intents: list[str]
    corpus: dict[str, list[list[str]]]


_model: ModelData | None = None


def _get_model() -> ModelData:
    global _model
    if _model is None:
        docs = [_normalize(d) for intents in CORPUS.values() for d in intents]
        _model = {
            "idf": _compute_idf(docs),
            "intents": list(CORPUS.keys()),
            "corpus": {k: [_normalize(d) for d in v] for k, v in CORPUS.items()},
        }
    return _model


class TfIdfResult(TypedDict):
    intent: str
    confidence: float


def classify_intent(text: str) -> TfIdfResult:
    if text == "/start":
        return {"intent": "saludo", "confidence": 1.0}

    model = _get_model()
    q_tokens = _normalize(text)
    if not q_tokens:
        return {"intent": INTENT_DESCONOCIDO, "confidence": 0.0}

    q_tf = _compute_tf(q_tokens)
    scores: list[tuple[float, str]] = []
    for intent in model["intents"]:
        max_s = max([_cosine_similarity(q_tf, _compute_tf(d), model["idf"]) for d in model["corpus"][intent]] or [0.0])
        scores.append((max_s, intent))

    scores.sort(reverse=True)
    top = scores[0][0]
    return {"intent": scores[0][1] if top > 0.1 else INTENT_DESCONOCIDO, "confidence": top}
