# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "google-adk[extensions]>=2.0.0",
#   "google-genai>=1.75.0",
#   "litellm>=1.71.2",
# ]
# ///
from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any, Final, cast

from google.adk import Agent, Runner
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .._wmill_adapter import log
from ._constants import GADK_APP_NAME, GADK_MODEL, GADK_MODEL_DISPLAY, INTENT

MODULE: Final[str] = "gadk_agent"


# ============================================================================
# NIVEL 1: Navegacion a menus principales
# ============================================================================


def _navegar_a_agendar(
    especialidad: str | None = None,
    fecha: str | None = None,
    doctor: str | None = None,
) -> str:
    """Inicia el flujo de agendamiento de cita medica en el sistema.

    Usa esta herramienta EXCLUSIVAMENTE cuando el usuario exprese de forma
    clara su deseo de agendar una cita medica. Frases tipicas que activan
    esta herramienta: 'quiero cita', 'quiero una hora', 'quiero agendar',
    'necesito reservar', 'agendar con el cardiologo', 'hora para el viernes'.

    NO uses esta herramienta para: consultas de citas existentes, cancelaciones,
    preguntas generales, saludos, o cualquier otra intencion que no sea crear
    una nueva cita. En esos casos usa otra herramienta especifica.

    Args:
        especialidad: Especialidad medica solicitada si el usuario la menciona
            explicitamente (ej: 'cardiologia', 'pediatria', 'odontologia').
            None si el usuario no especifica o dice 'cualquier especialidad'.
        fecha: Fecha preferida en formato libre si el usuario la menciona
            (ej: 'viernes', '2026-05-25', 'la proxima semana', 'el lunes').
            None si el usuario no indica preferencia de fecha.
        doctor: Nombre del profesional medico si el usuario lo solicita
            explicitamente (ej: 'doctor Martinez', 'la doctora Lopez').
            None si el usuario no especifica doctor.

    Returns:
        str: JSON serializado con:
            {"accion": "iniciar_agendamiento", "especialidad": str|None,
             "fecha": str|None, "doctor": str|None}.
            El sistema valida registro del usuario e inicia el FSM de booking.
    """
    return json.dumps(
        {
            "accion": "iniciar_agendamiento",
            "especialidad": especialidad,
            "fecha": fecha,
            "doctor": doctor,
        }
    )


def _navegar_a_mis_citas() -> str:
    """Muestra la lista de citas agendadas del usuario.

    Usa esta herramienta CUANDO el usuario quiera ver sus citas proximas,
    consultar el estado de una reserva, o revisar su historial de citas.
    Frases tipicas: 'ver mis citas', 'mis horas', 'tengo citas?',
    'cuando es mi proxima cita', 'lista de citas'.

    NO uses esta herramienta para: agendar nuevas citas, cancelar citas,
    o preguntas generales. El sistema validara que el usuario este registrado
    antes de mostrar la informacion. Si no esta registrado, se le pedira
    registro automaticamente.

    Returns:
        str: JSON serializado con:
            {"accion": "ver_mis_citas"}.
            El sistema valida client_id y retorna la lista de citas activas
            o un mensaje indicando que no hay citas programadas.
    """
    return json.dumps({"accion": "ver_mis_citas"})


def _navegar_a_recordatorios() -> str:
    """Abre el submenu de configuracion de recordatorios de citas.

    Usa esta herramienta CUANDO el usuario quiera configurar, activar,
    desactivar o modificar sus recordatorios de citas medicas.
    Frases tipicas: 'recordatorios', 'configurar recordatorios',
    'activar alertas', 'notificaciones', 'aviso antes de la cita'.

    NO uses esta herramienta para: ver citas agendadas, agendar nuevas citas,
    o preguntas generales. El sistema validara que el usuario este registrado
    antes de abrir el submenu de configuracion. Si no esta registrado,
    se le pedira registro automaticamente.

    Returns:
        str: JSON serializado con:
            {"accion": "configurar_recordatorios"}.
            El sistema valida client_id y muestra el teclado de configuracion
            de recordatorios (canales y ventanas de tiempo).
    """
    return json.dumps({"accion": "configurar_recordatorios"})


def _navegar_a_mis_datos() -> str:
    """Muestra los datos personales registrados del usuario.

    Usa esta herramienta CUANDO el usuario quiera ver o consultar su
    informacion personal registrada en el sistema. Frases tipicas:
    'mis datos', 'mi perfil', 'ver mis datos', 'que datos tienes de mi',
    'mi informacion personal'.

    NO uses esta herramienta para: actualizar datos (requiere contacto humano),
    agendar citas, o preguntas generales. El sistema validara que el usuario
    este registrado antes de mostrar la informacion. Si no esta registrado,
    se le iniciara el flujo de registro automaticamente.

    Returns:
        str: JSON serializado con:
            {"accion": "ver_mis_datos"}.
            El sistema valida client_id y muestra nombre, telefono y estado
            de registro, o inicia el flujo de registro si no existe.
    """
    return json.dumps({"accion": "ver_mis_datos"})


def _navegar_a_informacion() -> str:
    """Activa el modo de preguntas generales e informacion del sistema.

    Usa esta herramienta CUANDO el usuario haga preguntas que no estan
    relacionadas con agendar, cancelar o gestionar citas medicas.
    Frases tipicas: 'informacion', 'info', 'como funciona',
    'que especialidades tienen', 'donde estan ubicados', 'pregunta'.

    NO uses esta herramienta para: agendar citas, ver citas, cancelar,
    o cualquier accion operativa de booking. Este tool redirige al sistema
    de FAQ y respuestas informativas.

    Returns:
        str: JSON serializado con:
            {"accion": "ver_informacion"}.
            El sistema activa el modo de respuesta informativa con contexto
            RAG de FAQs del proveedor.
    """
    return json.dumps({"accion": "ver_informacion"})


# ============================================================================
# NIVEL 2: Navegacion directa a submenus y acciones especificas
# ============================================================================


def _seleccionar_especialidad(especialidad: str | None = None) -> str:
    """Redirige al submenu de seleccion de especialidad medica.

    Usa esta herramienta CUANDO el usuario quiera elegir una especialidad
    medica para agendar una cita, sin importar en que parte del flujo se
    encuentre actualmente. Frases tipicas: 'quiero cardiologia',
    'especialidad dermatologia', 'ver especialidades', 'otra especialidad',
    'cambiar de especialidad'.

    NO uses esta herramienta si el usuario ya esta en el proceso de seleccionar
    un doctor o un horario para una especialidad ya elegida. Si el usuario
    no esta registrado, el sistema mostrara un mensaje de error y lo redirigira
    al menu principal para iniciar el registro.

    Args:
        especialidad: Nombre de la especialidad medica si el usuario la
            menciona explicitamente (ej: 'cardiologia', 'dermatologia',
            'pediatria', 'medicina general'). None si el usuario quiere ver
            la lista completa de especialidades disponibles.

    Returns:
        str: JSON serializado con:
            {"accion": "seleccionar_especialidad", "especialidad": str|None}.
            El sistema valida client_id. Si no esta registrado, muestra error
            y redirige al menu principal. Si esta registrado, muestra la lista
            de especialidades o filtra por la especialidad solicitada.
    """
    return json.dumps(
        {
            "accion": "seleccionar_especialidad",
            "especialidad": especialidad,
        }
    )


def _cancelar_cita(booking_id: str | None = None) -> str:
    """Inicia el proceso de cancelacion de una cita medica existente.

    Usa esta herramienta CUANDO el usuario quiera cancelar una cita que ya
    tiene agendada. Frases tipicas: 'cancelar mi cita', 'anular la reserva',
    'ya no puedo ir', 'eliminar mi cita', 'cancelar la hora del martes'.

    NO uses esta herramienta para: agendar nuevas citas, reagendar citas
    existentes, o consultas generales. El sistema validara que el usuario
    este registrado y tenga citas activas. Si no tiene citas, se le informara
    y se le redirigira al menu principal.

    Args:
        booking_id: ID de la cita a cancelar si el usuario lo menciona
            explicitamente (formato UUID). None si el usuario no especifica
            cual cita cancelar; en ese caso el sistema mostrara la lista
            de citas activas para que elija.

    Returns:
        str: JSON serializado con:
            {"accion": "cancelar_cita", "booking_id": str|None}.
            El sistema valida client_id y citas activas. Si no cumple,
            muestra mensaje de error y redirige al menu principal.
    """
    return json.dumps(
        {
            "accion": "cancelar_cita",
            "booking_id": booking_id,
        }
    )


def _reagendar_cita(
    booking_id: str | None = None,
    fecha: str | None = None,
    doctor: str | None = None,
) -> str:
    """Inicia el proceso de reagendamiento de una cita medica existente.

    Usa esta herramienta CUANDO el usuario quiera cambiar la fecha u hora
    de una cita que ya tiene agendada. Frases tipicas: 'reagendar mi cita',
    'cambiar la fecha', 'mover la hora', 'reprogramar', 'otra fecha para
    mi cita', 'cambiar mi hora del martes'.

    NO uses esta herramienta para: agendar nuevas citas, cancelar citas,
    o consultas generales. El sistema validara que el usuario este registrado
    y tenga citas activas. Si no tiene citas, se le informara y se le
    redirigira al menu principal.

    Args:
        booking_id: ID de la cita a reagendar si el usuario lo menciona
            explicitamente (formato UUID). None si el usuario no especifica
            cual cita reagendar; el sistema mostrara la lista de citas activas.
        fecha: Nueva fecha preferida si el usuario la menciona (ej: 'viernes',
            '2026-05-25', 'la proxima semana'). None si no indica preferencia.
        doctor: Nuevo doctor preferido si el usuario lo solicita (ej: 'doctor
            Martinez'). None si no especifica cambio de doctor.

    Returns:
        str: JSON serializado con:
            {"accion": "reagendar_cita", "booking_id": str|None,
             "fecha": str|None, "doctor": str|None}.
            El sistema valida client_id y citas activas. Si no cumple,
            muestra mensaje de error y redirige al menu principal.
    """
    return json.dumps(
        {
            "accion": "reagendar_cita",
            "booking_id": booking_id,
            "fecha": fecha,
            "doctor": doctor,
        }
    )


def _configurar_canal_recordatorio(canal: str) -> str:
    """Activa o desactiva un canal especifico de recordatorio de citas.

    Usa esta herramienta CUANDO el usuario quiera activar o desactivar
    las notificaciones por un canal especifico (Telegram o email).
    Frases tipicas: 'activar recordatorio por telegram', 'desactivar
    email', 'no quiero notificaciones por correo', 'alertas por telegram'.

    NO uses esta herramienta para: configurar ventanas de tiempo de
    recordatorio, activar/desactivar todos los recordatorios de golpe,
    o gestionar citas. El sistema validara que el usuario este registrado.
    Si no esta registrado, mostrara error y redirigira al menu principal.

    Args:
        canal: Canal de notificacion a configurar. Valores validos:
            'telegram' (notificaciones por el bot de Telegram),
            'email' (notificaciones por correo electronico).

    Returns:
        str: JSON serializado con:
            {"accion": "configurar_canal_recordatorio", "canal": str}.
            El sistema valida client_id. Si no esta registrado, muestra
            error y redirige al menu principal. Si esta registrado,
            alterna el estado del canal especificado (on/off).
    """
    return json.dumps(
        {
            "accion": "configurar_canal_recordatorio",
            "canal": canal,
        }
    )


def _configurar_ventana_recordatorio(ventana: str) -> str:
    """Configura la ventana de tiempo para recibir recordatorios de citas.

    Usa esta herramienta CUANDO el usuario quiera especificar con cuanta
    antelacion quiere recibir los recordatorios de sus citas.
    Frases tipicas: 'aviso 24 horas antes', 'recordatorio 2 horas antes',
    'notificacion 30 minutos antes', 'aviso un dia antes'.

    NO uses esta herramienta para: activar/desactivar canales de notificacion,
    o gestionar citas. El sistema validara que el usuario este registrado.
    Si no esta registrado, mostrara error y redirigira al menu principal.

    Args:
        ventana: Ventana de tiempo para el recordatorio. Valores validos:
            '1day' (un dia antes a las 08:00), '24h' (24 horas antes),
            '12h' (12 horas antes), '6h' (6 horas antes), '2h' (2 horas antes),
            '1h' (1 hora antes), '30min' (30 minutos antes).

    Returns:
        str: JSON serializado con:
            {"accion": "configurar_ventana_recordatorio", "ventana": str}.
            El sistema valida client_id. Si no esta registrado, muestra
            error y redirige al menu principal. Si esta registrado,
            alterna el estado de la ventana especificada (on/off).
    """
    return json.dumps(
        {
            "accion": "configurar_ventana_recordatorio",
            "ventana": ventana,
        }
    )


def _activar_todos_recordatorios() -> str:
    """Activa todos los canales y ventanas de recordatorio disponibles.

    Usa esta herramienta CUANDO el usuario quiera recibir todas las
    notificaciones posibles para sus citas medicas. Frases tipicas:
    'activar todos los recordatorios', 'quiero todas las alertas',
    'activar todo', 'notificaciones completas'.

    NO uses esta herramienta para: desactivar recordatorios, configurar
    canales individuales, o gestionar citas. El sistema validara que el
    usuario este registrado. Si no esta registrado, mostrara error y
    redirigira al menu principal.

    Returns:
        str: JSON serializado con:
            {"accion": "activar_todos_recordatorios"}.
            El sistema valida client_id. Si no esta registrado, muestra
            error y redirige al menu principal. Si esta registrado,
            activa todos los canales (telegram, email) y todas las
            ventanas de tiempo disponibles.
    """
    return json.dumps({"accion": "activar_todos_recordatorios"})


def _desactivar_todos_recordatorios() -> str:
    """Desactiva todos los canales y ventanas de recordatorio.

    Usa esta herramienta CUANDO el usuario quiera dejar de recibir
    todas las notificaciones de sus citas medicas. Frases tipicas:
    'desactivar recordatorios', 'no quiero alertas', 'silenciar todo',
    'quitar notificaciones', 'no me avisen'.

    NO uses esta herramienta para: activar recordatorios, configurar
    canales individuales, o gestionar citas. El sistema validara que el
    usuario este registrado. Si no esta registrado, mostrara error y
    redirigira al menu principal.

    Returns:
        str: JSON serializado con:
            {"accion": "desactivar_todos_recordatorios"}.
            El sistema valida client_id. Si no esta registrado, muestra
            error y redirige al menu principal. Si esta registrado,
            desactiva todos los canales y ventanas de recordatorio.
    """
    return json.dumps({"accion": "desactivar_todos_recordatorios"})


# ============================================================================
# COMODIN: Clasificacion de intenciones sin herramienta especifica
# ============================================================================


def _clasificar_intent(
    intent: str,
    confianza: float,
    especialidad: str | None = None,
    fecha: str | None = None,
    hora: str | None = None,
    booking_id: str | None = None,
    doctor: str | None = None,
    pregunta: str | None = None,
    es_urgente: bool = False,
) -> str:
    """Clasifica la intencion del usuario y extrae entidades de su mensaje.

    Usa esta herramienta como COMODIN para intenciones que no tienen una
    herramienta de navegacion dedicada. Incluye: saludo, despedida,
    agradecimiento, urgencia, pregunta_general, mostrar_menu_principal,
    desconocido.

    NO uses esta herramienta si existe una herramienta de navegacion especifica
    para la intencion detectada. En ese caso, usa la herramienta especifica
    (_navegar_a_agendar, _cancelar_cita, etc).

    Args:
        intent: Identificador de la intencion detectada. Valores validos:
            'saludo', 'despedida', 'agradecimiento', 'urgencia',
            'pregunta_general', 'mostrar_menu_principal', 'desconocido'.
        confianza: Nivel de certeza entre 0.0 y 1.0. Usa 0.95 para saludos/
            despedidas simples, 0.9 cuando estes seguro, 0.5 si hay ambiguedad.
        especialidad: Especialidad medica mencionada (ej: 'cardiologia').
            None si no se menciona.
        fecha: Fecha mencionada por el usuario en formato libre.
            None si no se menciona.
        hora: Hora mencionada (ej: '10:00'). None si no aplica.
        booking_id: ID de una cita existente cuando el usuario se refiere a ella.
            None si no aplica.
        doctor: Nombre del profesional medico mencionado. None si no se menciona.
        pregunta: Texto completo de la pregunta cuando el intent es
            'pregunta_general'. None para otros intents.
        es_urgente: True cuando el usuario indica una emergencia medica que
            requiere atencion inmediata. False en todos los demas casos.

    Returns:
        str: JSON serializado con la estructura:
            {"intent": str, "confianza": float, "entidades": dict}.
            El sistema parsea este JSON para decidir el siguiente paso del flow.
    """
    entidades: dict[str, str | None | bool] = {
        "especialidad": especialidad,
        "fecha": fecha,
        "hora": hora,
        "booking_id": booking_id,
        "doctor": doctor,
        "pregunta": pregunta,
        "es_urgente": es_urgente,
    }
    return json.dumps(
        {
            "intent": intent,
            "confianza": confianza,
            "entidades": entidades,
        }
    )


# ============================================================================
# AGENTE GADK
# ============================================================================

_NAVIGATION_TOOLS = [
    # Nivel 1: Menus principales
    _navegar_a_agendar,
    _navegar_a_mis_citas,
    _navegar_a_recordatorios,
    _navegar_a_mis_datos,
    _navegar_a_informacion,
    # Nivel 2: Submenus y acciones especificas
    _seleccionar_especialidad,
    _cancelar_cita,
    _reagendar_cita,
    _configurar_canal_recordatorio,
    _configurar_ventana_recordatorio,
    _activar_todos_recordatorios,
    _desactivar_todos_recordatorios,
    # Comodin
    _clasificar_intent,
]

_INSTRUCTION: Final[str] = (
    "Eres un clasificador de intenciones para un sistema de reservas medicas por Telegram. "
    "Tu unica tarea es analizar el mensaje del usuario y llamar a la herramienta correcta.\n\n"
    "HERRAMIENTAS DE NAVEGACION NIVEL 1 (menus principales):\n"
    "1. `_navegar_a_agendar`: Agendar cita nueva.\n"
    "   Frases: 'quiero cita', 'quiero una hora', 'quiero agendar'.\n"
    "2. `_navegar_a_mis_citas`: Ver citas agendadas.\n"
    "   Frases: 'ver mis citas', 'mis horas', 'mi proxima cita'.\n"
    "3. `_navegar_a_recordatorios`: Configurar recordatorios.\n"
    "   Frases: 'recordatorios', 'configurar alertas', 'notificaciones'.\n"
    "4. `_navegar_a_mis_datos`: Ver datos personales.\n"
    "   Frases: 'mis datos', 'mi perfil', 'mi informacion'.\n"
    "5. `_navegar_a_informacion`: Preguntas generales.\n"
    "   Frases: 'informacion', 'info', 'como funciona'.\n\n"
    "HERRAMIENTAS DE NAVEGACION NIVEL 2 (submenus y acciones):\n"
    "6. `_seleccionar_especialidad`: Ir directo a elegir especialidad.\n"
    "   Frases: 'quiero cardiologia', 'ver especialidades', 'otra especialidad'.\n"
    "7. `_cancelar_cita`: Cancelar una cita existente.\n"
    "   Frases: 'cancelar mi cita', 'anular la reserva', 'ya no puedo ir'.\n"
    "8. `_reagendar_cita`: Cambiar fecha/hora de cita existente.\n"
    "   Frases: 'reagendar', 'cambiar la fecha', 'mover la hora', 'reprogramar'.\n"
    "9. `_configurar_canal_recordatorio`: Activar/desactivar canal (telegram/email).\n"
    "   Frases: 'activar telegram', 'desactivar email', 'alertas por correo'.\n"
    "10. `_configurar_ventana_recordatorio`: Configurar anticipacion de aviso.\n"
    "    Frases: 'aviso 24 horas antes', 'recordatorio 2 horas antes'.\n"
    "11. `_activar_todos_recordatorios`: Activar todas las notificaciones.\n"
    "    Frases: 'activar todo', 'quiero todas las alertas'.\n"
    "12. `_desactivar_todos_recordatorios`: Desactivar todas las notificaciones.\n"
    "    Frases: 'desactivar recordatorios', 'no quiero alertas', 'silenciar todo'.\n\n"
    "HERRAMIENTA COMODIN (ultimo recurso):\n"
    "13. `_clasificar_intent`: SOLO para intenciones sin herramienta especifica:\n"
    "    saludo, despedida, agradecimiento, urgencia, mostrar_menu_principal, desconocido.\n\n"
    "REGLAS:\n"
    "1. SIEMPRE prefiere una herramienta especifica sobre `_clasificar_intent`.\n"
    "2. NUNCA respondas con texto libre, SIEMPRE llama a una herramienta.\n"
    "3. Extrae entidades del texto: especialidad, fecha, hora, doctor, booking_id.\n"
    "4. Si el usuario menciona urgencia medica, usa intent='urgencia' y es_urgente=True.\n"
    "5. Si es un saludo/despedida/agradecimiento simple, confianza=0.95.\n"
    "6. Si hay ambiguedad, confianza=0.5. Si estas seguro, confianza=0.9.\n"
    "7. Para pregunta_general, incluye el texto de la pregunta en el parametro 'pregunta'."
)

_agent_cache: Agent | None = None
_runner_cache: Runner | None = None


def _get_agent() -> Agent:
    global _agent_cache
    if _agent_cache is None:
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        _agent_cache = Agent(
            name=f"booking_classifier_{int(time.time())}",
            model=LiteLlm(model=GADK_MODEL, api_key=openrouter_key),
            instruction=_INSTRUCTION,
            tools=cast("list[Any]", _NAVIGATION_TOOLS),
        )
    return _agent_cache


def _get_runner() -> Runner:
    global _runner_cache
    if _runner_cache is None:
        session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
        _runner_cache = Runner(
            agent=_get_agent(),
            app_name=GADK_APP_NAME,
            session_service=session_service,
            auto_create_session=True,
        )
    return _runner_cache


_NAVIGATION_MAP: Final[dict[str, dict[str, Any]]] = {
    "_navegar_a_agendar": {
        "intent": INTENT["CREAR_CITA"],
        "confidence": 0.95,
    },
    "_navegar_a_mis_citas": {
        "intent": INTENT["VER_MIS_CITAS"],
        "confidence": 0.95,
    },
    "_navegar_a_recordatorios": {
        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
        "confidence": 0.95,
    },
    "_navegar_a_mis_datos": {
        "intent": INTENT["VER_MIS_DATOS"],
        "confidence": 0.95,
    },
    "_navegar_a_informacion": {
        "intent": INTENT["PREGUNTA_GENERAL"],
        "confidence": 0.95,
    },
    "_seleccionar_especialidad": {
        "intent": INTENT["CREAR_CITA"],
        "confidence": 0.95,
    },
    "_cancelar_cita": {
        "intent": INTENT["CANCELAR_CITA"],
        "confidence": 0.95,
    },
    "_reagendar_cita": {
        "intent": INTENT["REAGENDAR_CITA"],
        "confidence": 0.95,
    },
    "_configurar_canal_recordatorio": {
        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
        "confidence": 0.95,
    },
    "_configurar_ventana_recordatorio": {
        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
        "confidence": 0.95,
    },
    "_activar_todos_recordatorios": {
        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
        "confidence": 0.95,
    },
    "_desactivar_todos_recordatorios": {
        "intent": INTENT["DESACTIVAR_RECORDATORIOS"],
        "confidence": 0.95,
    },
}


async def classify_with_gadk(text: str, chat_id: str) -> dict[str, Any] | None:
    """Clasifica intencion usando Google ADK + LiteLlm + OpenRouter (Nemotron 3 Super).

    Returns dict with intent, confidence, entities or None if failed.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        log("GADK_NO_OPENROUTER_KEY", module=MODULE)
        return None

    log(f"GADK_START | model={GADK_MODEL_DISPLAY} | text={text[:50]}", module=MODULE)

    runner = _get_runner()
    content = types.Content(role="user", parts=[types.Part(text=text)])

    try:
        async for event in runner.run_async(
            user_id=chat_id,
            session_id=f"session_{chat_id}",
            new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text and not getattr(part, "thought", False):
                        try:
                            result = json.loads(part.text)
                            accion = result.get("accion")
                            if accion and accion != "clasificar":
                                # Nivel 1
                                if accion == "iniciar_agendamiento":
                                    return {
                                        "intent": INTENT["CREAR_CITA"],
                                        "confidence": 0.95,
                                        "entities": {
                                            "especialidad": result.get("especialidad"),
                                            "fecha": result.get("fecha"),
                                            "hora": None,
                                            "doctor": result.get("doctor"),
                                            "booking_id": None,
                                            "pregunta": None,
                                            "es_urgente": False,
                                        },
                                        "navigate_to_booking": True,
                                    }
                                if accion == "ver_mis_citas":
                                    return {
                                        "intent": INTENT["VER_MIS_CITAS"],
                                        "confidence": 0.95,
                                        "entities": {},
                                    }
                                if accion == "configurar_recordatorios":
                                    return {
                                        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
                                        "confidence": 0.95,
                                        "entities": {},
                                    }
                                if accion == "ver_mis_datos":
                                    return {
                                        "intent": INTENT["VER_MIS_DATOS"],
                                        "confidence": 0.95,
                                        "entities": {},
                                    }
                                if accion == "ver_informacion":
                                    return {
                                        "intent": INTENT["PREGUNTA_GENERAL"],
                                        "confidence": 0.95,
                                        "entities": {},
                                    }
                                # Nivel 2
                                if accion == "seleccionar_especialidad":
                                    return {
                                        "intent": INTENT["CREAR_CITA"],
                                        "confidence": 0.95,
                                        "entities": {
                                            "especialidad": result.get("especialidad"),
                                            "fecha": None,
                                            "hora": None,
                                            "doctor": None,
                                            "booking_id": None,
                                            "pregunta": None,
                                            "es_urgente": False,
                                        },
                                        "navigate_to_booking": True,
                                    }
                                if accion == "cancelar_cita":
                                    return {
                                        "intent": INTENT["CANCELAR_CITA"],
                                        "confidence": 0.95,
                                        "entities": {
                                            "booking_id": result.get("booking_id"),
                                        },
                                    }
                                if accion == "reagendar_cita":
                                    return {
                                        "intent": INTENT["REAGENDAR_CITA"],
                                        "confidence": 0.95,
                                        "entities": {
                                            "booking_id": result.get("booking_id"),
                                            "fecha": result.get("fecha"),
                                            "doctor": result.get("doctor"),
                                        },
                                    }
                                if accion == "configurar_canal_recordatorio":
                                    return {
                                        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
                                        "confidence": 0.95,
                                        "entities": {
                                            "channel": result.get("canal"),
                                        },
                                    }
                                if accion == "configurar_ventana_recordatorio":
                                    return {
                                        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
                                        "confidence": 0.95,
                                        "entities": {
                                            "reminder_window": result.get("ventana"),
                                        },
                                    }
                                if accion == "activar_todos_recordatorios":
                                    return {
                                        "intent": INTENT["ACTIVAR_RECORDATORIOS"],
                                        "confidence": 0.95,
                                        "entities": {},
                                    }
                                if accion == "desactivar_todos_recordatorios":
                                    return {
                                        "intent": INTENT["DESACTIVAR_RECORDATORIOS"],
                                        "confidence": 0.95,
                                        "entities": {},
                                    }
                            return {
                                "intent": result.get("intent", INTENT["DESCONOCIDO"]),
                                "confidence": float(result.get("confianza", 0.0)),
                                "entities": result.get("entidades", {}),
                            }
                        except (json.JSONDecodeError, ValueError) as e:
                            log(f"GADK_JSON_ERROR | error={e}", module=MODULE)
                            return None
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        try:
                            raw_args = fc.args if fc.args else "{}"
                            args: dict[str, Any] = (
                                json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                            )
                            fc_name = fc.name or ""
                            nav_config = _NAVIGATION_MAP.get(fc_name)
                            if nav_config:
                                entities: dict[str, Any] = {}
                                if fc_name == "_navegar_a_agendar":
                                    entities = {
                                        "especialidad": args.get("especialidad"),
                                        "fecha": args.get("fecha"),
                                        "hora": None,
                                        "doctor": args.get("doctor"),
                                        "booking_id": None,
                                        "pregunta": None,
                                        "es_urgente": False,
                                    }
                                elif fc_name == "_seleccionar_especialidad":
                                    entities = {
                                        "especialidad": args.get("especialidad"),
                                        "fecha": None,
                                        "hora": None,
                                        "doctor": None,
                                        "booking_id": None,
                                        "pregunta": None,
                                        "es_urgente": False,
                                    }
                                elif fc_name == "_cancelar_cita":
                                    entities = {"booking_id": args.get("booking_id")}
                                elif fc_name == "_reagendar_cita":
                                    entities = {
                                        "booking_id": args.get("booking_id"),
                                        "fecha": args.get("fecha"),
                                        "doctor": args.get("doctor"),
                                    }
                                elif fc_name == "_configurar_canal_recordatorio":
                                    entities = {"channel": args.get("canal")}
                                elif fc_name == "_configurar_ventana_recordatorio":
                                    entities = {"reminder_window": args.get("ventana")}
                                return {
                                    "intent": nav_config["intent"],
                                    "confidence": nav_config["confidence"],
                                    "entities": entities,
                                    "navigate_to_booking": (
                                        fc_name in ("_navegar_a_agendar", "_seleccionar_especialidad")
                                    ),
                                }
                            return {
                                "intent": args.get("intent", INTENT["DESCONOCIDO"]),
                                "confidence": float(args.get("confianza", 0.0)),
                                "entities": {
                                    "especialidad": args.get("especialidad"),
                                    "fecha": args.get("fecha"),
                                    "hora": args.get("hora"),
                                    "doctor": args.get("doctor"),
                                    "booking_id": args.get("booking_id"),
                                    "pregunta": args.get("pregunta"),
                                    "es_urgente": args.get("es_urgente", False),
                                },
                            }
                        except (json.JSONDecodeError, ValueError, TypeError) as e:
                            log(f"GADK_TOOL_ARGS_ERROR | error={e}", module=MODULE)
                            return None
    except Exception as e:
        tb = traceback.format_exc()
        log(f"GADK_EXCEPTION | error={e} | traceback={tb}", module=MODULE)
        return None

    return None
