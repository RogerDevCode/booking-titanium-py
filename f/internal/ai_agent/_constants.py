from typing import Final, Literal, TypedDict

# ============================================================================
# INTENT CONSTANTS — Single Source of Truth (v3)
# ============================================================================

IntentType = Literal[
    "crear_cita",
    "cancelar_cita",
    "reagendar_cita",
    "ver_disponibilidad",
    "urgencia",
    "pregunta_general",
    "saludo",
    "despedida",
    "agradecimiento",
    "activar_recordatorios",
    "desactivar_recordatorios",
    "preferencias_recordatorio",
    "mostrar_menu_principal",
    "paso_wizard",
    "ver_mis_citas",
    "ver_mis_datos",
    "generar_reporte",
    "desconocido",
]


class IntentsStruct(TypedDict):
    CREAR_CITA: Literal["crear_cita"]
    CANCELAR_CITA: Literal["cancelar_cita"]
    REAGENDAR_CITA: Literal["reagendar_cita"]
    VER_DISPONIBILIDAD: Literal["ver_disponibilidad"]
    URGENCIA: Literal["urgencia"]
    PREGUNTA_GENERAL: Literal["pregunta_general"]
    SALUDO: Literal["saludo"]
    DESPEDIDA: Literal["despedida"]
    AGRADECIMIENTO: Literal["agradecimiento"]
    ACTIVAR_RECORDATORIOS: Literal["activar_recordatorios"]
    DESACTIVAR_RECORDATORIOS: Literal["desactivar_recordatorios"]
    PREFERENCIAS_RECORDATORIO: Literal["preferencias_recordatorio"]
    MOSTRAR_MENU_PRINCIPAL: Literal["mostrar_menu_principal"]
    PASO_WIZARD: Literal["paso_wizard"]
    VER_MIS_CITAS: Literal["ver_mis_citas"]
    VER_MIS_DATOS: Literal["ver_mis_datos"]
    GENERAR_REPORTE: Literal["generar_reporte"]
    DESCONOCIDO: Literal["desconocido"]


INTENT: Final[IntentsStruct] = {
    "CREAR_CITA": "crear_cita",
    "CANCELAR_CITA": "cancelar_cita",
    "REAGENDAR_CITA": "reagendar_cita",
    "VER_DISPONIBILIDAD": "ver_disponibilidad",
    "URGENCIA": "urgencia",
    "PREGUNTA_GENERAL": "pregunta_general",
    "SALUDO": "saludo",
    "DESPEDIDA": "despedida",
    "AGRADECIMIENTO": "agradecimiento",
    "ACTIVAR_RECORDATORIOS": "activar_recordatorios",
    "DESACTIVAR_RECORDATORIOS": "desactivar_recordatorios",
    "PREFERENCIAS_RECORDATORIO": "preferencias_recordatorio",
    "MOSTRAR_MENU_PRINCIPAL": "mostrar_menu_principal",
    "PASO_WIZARD": "paso_wizard",
    "VER_MIS_CITAS": "ver_mis_citas",
    "VER_MIS_DATOS": "ver_mis_datos",
    "GENERAR_REPORTE": "generar_reporte",
    "DESCONOCIDO": "desconocido",
}

ESCALATION_THRESHOLDS: Final[dict[str, float]] = {
    "medical_emergency_min": 0.8,
    "priority_queue_max": 0.6,
    "human_handoff_max": 0.4,
    "tfidf_minimum": 0.4,
}

CONFIDENCE_BOUNDARIES: Final[dict[str, float]] = {
    "HIGH_MIN": 0.85,
    "MODERATE_MIN": 0.60,
    "MODERATE_MAX": 0.85,
    "LOW_MAX": 0.60,
}

CONFIDENCE_THRESHOLDS: Final[dict[str, float]] = {
    "medical_emergency_min": 0.8,
    "priority_queue_max": 0.6,
    "human_handoff_max": 0.4,
    "tfidf_minimum": 0.4,
    "urgencia": 0.5,
}

FAREWELLS: Final[list[str]] = ["adios", "adiós", "chao"]
FAREWELL_PHRASES: Final[list[str]] = ["hasta luego", "nos vemos"]
GREETINGS: Final[list[str]] = ["hola", "buenas", "saludos"]
GREETING_PHRASES: Final[list[str]] = ["buenos dias", "buen dia"]
THANK_YOU_WORDS: Final[list[str]] = ["gracias", "muchas gracias"]
URGENCY_WORDS: Final[list[str]] = ["urgencia", "urgente", "emergencia", "rapido"]
FLEXIBILITY_KEYWORDS: Final[list[str]] = ["cambio", "otra", "reagendar"]
DAY_NAMES: Final[dict[str, str]] = {
    "lunes": "Lunes",
    "martes": "Martes",
    "miercoles": "Miércoles",
    "jueves": "Jueves",
    "viernes": "Viernes",
    "sabado": "Sábado",
    "domingo": "Domingo",
}
RELATIVE_DATES: Final[list[str]] = ["hoy", "mañana", "manana"]
SERVICE_TYPES: Final[list[str]] = ["medicina general", "cardiologia", "dermatologia"]
RULE_CONFIDENCE_VALUES: Final[dict[str, float]] = {
    "greeting_exact": 0.95,
    "greeting_phrase": 0.9,
    "farewell_exact": 0.95,
    "farewell_phrase": 0.9,
    "urgencia_medical": 0.9,
}
SOCIAL_CONFIDENCE_VALUES: Final[dict[str, float]] = {
    "greeting_exact": 0.95,
    "greeting_phrase": 0.9,
    "farewell_exact": 0.95,
    "farewell_phrase": 0.9,
}
INTENT_KEYWORDS: Final[dict[str, list[str]]] = {
    "saludo": ["hola", "buenas", "buenos dias", "buen dia", "saludos"],
    "urgencia": ["urgencia", "emergencia", "ayuda", "socorro", "rapido"],
    "crear_cita": ["agendar", "reservar", "programar", "1"],
    "ver_mis_citas": ["mis citas", "ver citas", "mis reservas", "2"],
    "cancelar_cita": ["cancelar", "cancelar hora", "cancelar cita", "anular hora", "3"],
    "reagendar_cita": ["reagendar", "reagendar hora", "cambiar hora", "reprogramar", "4"],
    "generar_reporte": ["reporte", "informe", "descargar citas", "obtener reporte", "5"],
    "activar_recordatorios": ["6", "recordatorios"],
    "pregunta_general": ["7", "informacion", "info"],
    "ver_mis_datos": ["mis datos", "datos", "mi perfil", "perfil", "8"],
    "despedida": ["adios", "bye", "hasta luego", "chao"],
    "agradecimiento": ["gracias", "muchas gracias"],
    "mostrar_menu_principal": ["menu", "inicio", "volver"],
}
NORMALIZATION_MAP: Final[dict[str, str]] = {
    "ajendar": "agendar",
    "cancelar": "cancelar",
}
PROFANITY_TO_IGNORE: Final[list[str]] = []
OFF_TOPIC_PATTERNS: Final[list[str]] = []

# ============================================================================
# GADK MODEL CONFIGURATION — Single Source of Truth
# ============================================================================

GADK_MODEL: Final[str] = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
GADK_MODEL_DISPLAY: Final[str] = "nemotron-3-super-120b:free"
GADK_APP_NAME: Final[str] = "booking_classifier"
