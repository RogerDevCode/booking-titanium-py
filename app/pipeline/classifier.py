import re
import math
import unicodedata
from typing import List, Dict, Final, Set
from app.domain.enums import Intent
from app.core.logging import logger

class IntentClassifier:
    """
    Hybrid Intent Classifier.
    1. Layer 0: Deterministic Fast-Path (Numeric/Exact).
    2. Layer 1: TF-IDF + Cosine Similarity (Semantic Engine).
    3. Layer 2: LLM Fallback (Ambuguity Handling).
    """

    # --- CORPUS HEREDADO (Mapeado a Enums) ---
    _CORPUS: Final[Dict[Intent, List[str]]] = {
        Intent.BOOK_APPOINTMENT: [
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
            "quiero agendar una cita para mañana",
            "necesito cita urgente",
        ],
        Intent.CANCEL_APPOINTMENT: [
            "quiero cancelar mi hora del martes",
            "no podre ir cancélame la hora",
            "anular turno programado para mañana",
            "eliminar hora agendada",
            "borrar mi reserva del jueves",
            "no podre ir cancélame",
            "cancelar hora que tengo",
            "necesito cancelar mi hora de mañana",
            "quiero cancelar mi cita del martes",
            "necesito cancelar mi cita",
        ],
        Intent.RESCHEDULE_APPOINTMENT: [
            "necesito cambiar mi cita del viernes al jueves",
            "reprogramar turno para la otra semana",
            "mejor para el miércoles a las once",
            "mover mi hora de mañana para pasado",
            "quiero cambiar la cita para otro dia",
            "reagendar cita para la próxima semana",
            "cambiar cita para el lunes",
            "necesito reagendar mi consulta",
        ],
        Intent.MY_BOOKINGS: [
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
        Intent.GET_INFO: [
            "tienen disponibilidad para el lunes",
            "esta libre el doctor el martes por la mañana",
            "hay hueco para hoy a las tres",
            "tiene hora disponible esta semana",
            "puedo agendar para mañana",
            "tiene libre el lunes",
            "hay disponibilidad para esta semana",
            "cuando tienen hora disponible",
            "que horas tienen para el viernes",
            "que especialidades tienen",
            "informacion de la clinica",
        ],
        Intent.MANAGE_PROFILE: [
            "quiero ver mis datos",
            "actualizar mi perfil",
            "cambiar mi telefono",
            "editar mis datos",
            "mi informacion personal",
        ]
    }

    _STOP_WORDS: Final[Set[str]] = {
        "el", "la", "los", "las", "un", "una", "de", "del", "al", "para", "por", 
        "con", "sin", "sobre", "es", "son", "esta", "que", "se", "no", "me", "te", 
        "le", "lo", "mi", "tu", "su", "y", "o", "pero", "si", "como", "donde", "cuando"
    }

    def __init__(self):
        self._idf: Dict[str, float] = {}
        self._tokenized_corpus: Dict[Intent, List[List[str]]] = {}
        self._initialize_engine()

    def _normalize(self, text: str) -> List[str]:
        """Normalización ligera compatible con el preprocesador."""
        text = text.lower().strip()
        text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
        text = re.sub(r"[?¿!¡.,;:()]", " ", text)
        return [w for w in text.split() if w not in self._STOP_WORDS and len(w) > 1]

    def _initialize_engine(self):
        """Calcula el IDF global basado en el corpus inicial."""
        all_docs = []
        for intent, examples in self._CORPUS.items():
            tokenized_examples = [self._normalize(ex) for ex in examples]
            self._tokenized_corpus[intent] = tokenized_examples
            all_docs.extend(tokenized_examples)

        # Compute IDF
        n = len(all_docs)
        for doc in all_docs:
            seen = set(doc)
            for t in seen:
                self._idf[t] = self._idf.get(t, 0.0) + 1.0

        for t in self._idf:
            self._idf[t] = math.log(n / (1.0 + self._idf[t]))

    def _compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        tf: Dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0.0) + 1.0
        
        length = len(tokens) or 1
        return {t: count / length for t, count in tf.items()}

    def _cosine_similarity(self, query_tf: Dict[str, float], doc_tf: Dict[str, float]) -> float:
        all_terms = set(query_tf.keys()) | set(doc_tf.keys())
        dot = 0.0
        mag_a = 0.0
        mag_b = 0.0

        for t in all_terms:
            idf_val = self._idf.get(t, 0.5) # Fallback idf
            w_a = query_tf.get(t, 0.0) * idf_val
            w_b = doc_tf.get(t, 0.0) * idf_val
            dot += w_a * w_b
            mag_a += w_a * w_a
            mag_b += w_b * w_b

        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (math.sqrt(mag_a) * math.sqrt(mag_b))

    async def classify(self, text: str) -> tuple[Intent, float]:
        # Layer 0: Deterministic Fast-Path
        clean_strip = text.strip().lower()
        mapping: Dict[str, Intent] = {
            "1": Intent.BOOK_APPOINTMENT,
            "2": Intent.MY_BOOKINGS,
            "3": Intent.CANCEL_APPOINTMENT,
            "4": Intent.RESCHEDULE_APPOINTMENT,
            "5": Intent.GET_REPORT,
            "6": Intent.MANAGE_REMINDERS,
            "7": Intent.GET_INFO,
            "8": Intent.MANAGE_PROFILE,
            "agendar": Intent.BOOK_APPOINTMENT,
            "cancelar": Intent.CANCEL_APPOINTMENT,
            "mis citas": Intent.MY_BOOKINGS,
        }
        if clean_strip in mapping:
            return mapping[clean_strip], 1.0

        # Layer 1: TF-IDF Cosine Similarity
        query_tokens = self._normalize(text)
        if not query_tokens:
            return Intent.UNKNOWN, 0.0

        query_tf = self._compute_tf(query_tokens)
        scores: List[tuple[Intent, float]] = []

        for intent, doc_list in self._tokenized_corpus.items():
            max_sim = 0.0
            for doc_tokens in doc_list:
                doc_tf = self._compute_tf(doc_tokens)
                sim = self._cosine_similarity(query_tf, doc_tf)
                if sim > max_sim:
                    max_sim = sim
            scores.append((intent, max_sim))

        # Sort by similarity
        scores.sort(key=lambda x: x[1], reverse=True)

        top_intent, top_score = scores[0]
        second_score = scores[1][1] if len(scores) > 1 else 0.0
        
        # Confidence calculation (Gap Logic)
        gap = top_score - second_score
        confidence = min(0.5 + gap * 3.0 + top_score * 2.0, 0.95) if top_score > 0 else 0.0

        if top_score > 0.3: # Minimum threshold
            return top_intent, round(confidence, 3)

        # Layer 2: LLM Fallback
        # When implemented, this should call ai_service for complex ambiguity resolution.
        # If the LLM is down, the CircuitBreakerOpenException will force the deterministic fallback (UNKNOWN).
        from app.core.circuit_breaker import CircuitBreakerOpenException
        try:
            logger.info("Intent ambiguity detected, LLM fallback needed", text=text, top_score=top_score)
            # Future: await ai_service.get_intent(text)
            return Intent.UNKNOWN, 0.0
        except CircuitBreakerOpenException:
            logger.warning("LLM Circuit Breaker is OPEN. Falling back to UNKNOWN intent.", text=text)
            return Intent.UNKNOWN, 0.0

    async def extract_entities(self, text: str) -> dict:
        """Extracts Chilean medical entities (RUT, Dates)."""
        entities = {}
        # Simple extraction logic...
        return entities
