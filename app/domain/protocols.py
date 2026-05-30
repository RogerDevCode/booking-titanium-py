"""
Protocolos (Contratos) para Inyección de Dependencias.

Cada Protocol define la interfaz estructural que una implementación
debe satisfacer.  Estos contratos son la especificación formal que
permite desacoplar los módulos y habilitar testing sin infraestructura.

REGLAS:
  1. Los protocolos SOLO importan tipos del dominio (app.domain.*).
  2. Los protocolos NO importan implementaciones concretas.
  3. Cada firma debe coincidir EXACTAMENTE con la implementación actual.
  4. @runtime_checkable se usa solo en boundaries I/O donde se
     necesite isinstance() según las reglas de RUNTIME TYPE ENFORCEMENT.
"""
from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from app.domain.entities import (
    AppointmentSlot,
    Booking,
    BookingView,
    Provider,
    Specialty,
    TelegramUser,
    ReminderPreferences,
)
from app.domain.models import ConversationState


# ═══════════════════════════════════════════════════════════════════════════
# CAPA DE INFRAESTRUCTURA
# ═══════════════════════════════════════════════════════════════════════════


@runtime_checkable
class DatabaseClientProtocol(Protocol):
    """
    Contrato para el cliente de base de datos PostgreSQL.

    Expone pool, transacciones y métodos de ejecución SQL.
    El pool se expone como Any para no acoplar al driver (asyncpg).
    """

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    @property
    def pool(self) -> Any:
        """Retorna el pool de conexiones subyacente (asyncpg.Pool)."""
        ...

    def transaction(self) -> AbstractAsyncContextManager[Any]:
        """
        Context manager de transacción.  Propaga la conexión vía
        contextvars para que queries internas participen de la misma tx.
        """
        ...

    async def execute(self, query: str, *args: Any) -> str:
        """Ejecuta un query sin retorno de filas.  Devuelve status string."""
        ...

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        """Ejecuta un query y retorna todas las filas."""
        ...

    async def fetchrow(self, query: str, *args: Any) -> Optional[Any]:
        """Ejecuta un query y retorna la primera fila, o None."""
        ...


@runtime_checkable
class RedisClientProtocol(Protocol):
    """
    Contrato para el cliente Redis.

    Expone conexión, el cliente nativo y lock distribuido por chat_id.
    """

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    @property
    def client(self) -> Any:
        """Retorna el cliente Redis nativo (redis.asyncio.Redis)."""
        ...

    async def get_arq_pool(self) -> Any:
        """Retorna el pool de conexiones arq (ArqRedis)."""
        ...

    def get_chat_lock(
        self, chat_id: int, timeout: int = 30
    ) -> AbstractAsyncContextManager[None]:
        """Lock distribuido por chat_id para serialización de mensajes."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# CAPA DE REPOSITORIOS
# ═══════════════════════════════════════════════════════════════════════════


class BookingRepositoryProtocol(Protocol):
    """
    Contrato para el repositorio de reservas.

    Solo SQL, sin reglas de negocio.  Los métodos con sufijo ``_tx``
    gestionan su propia transacción interna con ``pool.acquire()``.
    """

    async def get_user_bookings_view(
        self, user_id: int
    ) -> List[BookingView]: ...

    async def cancel_booking_tx(
        self, user_id: int, booking_id: int
    ) -> Optional[str]: ...

    async def reschedule_booking_tx(
        self, user_id: int, old_booking_id: int, new_slot_id: str
    ) -> tuple[Booking, str]: ...

    async def get_all_specialties(self) -> List[Specialty]: ...

    async def get_providers_by_specialty(
        self, specialty_id: str
    ) -> List[Provider]: ...

    async def get_available_slots(
        self, provider_id: str, limit: int = 15
    ) -> List[AppointmentSlot]: ...

    async def create_booking_tx(
        self, user_id: int, slot_id: str
    ) -> Booking: ...

    async def get_provider_id_by_booking(
        self, booking_id: int
    ) -> str: ...

    async def add_to_waitlist(
        self, user_id: int, provider_id: str
    ) -> None: ...

    async def get_provider_id_by_slot(
        self, slot_id: str
    ) -> Optional[str]: ...

    async def get_history_by_month(
        self, user_id: int, year: int, month: int
    ) -> List[BookingView]: ...

    async def get_history_all(
        self, user_id: int
    ) -> List[BookingView]: ...


class ConversationTransactionProtocol(Protocol):
    """
    Contrato para el manejo transaccional del estado de conversación.

    Lee y persiste ``ConversationState`` usando advisory locks para
    garantizar serialización por ``chat_id``.
    """

    async def get_state(self, chat_id: int) -> ConversationState: ...

    async def set_state(self, state: ConversationState) -> None: ...


# ═══════════════════════════════════════════════════════════════════════════
# CAPA DE SERVICIOS
# ═══════════════════════════════════════════════════════════════════════════


class BookingServiceProtocol(Protocol):
    """
    Contrato para el servicio de reservas (lógica de negocio).

    Delega persistencia al repositorio; no contiene SQL directo.
    """

    async def get_user_bookings(
        self, user_id: int
    ) -> List[BookingView]: ...

    async def cancel_booking(
        self, user_id: int, booking_id: int
    ) -> Optional[str]: ...

    async def reschedule_booking(
        self, user_id: int, old_booking_id: int, new_slot_id: str
    ) -> tuple[Booking, str]: ...

    async def get_all_specialties(self) -> List[Specialty]: ...

    async def get_providers_by_specialty(
        self, specialty_id: str
    ) -> List[Provider]: ...

    async def get_available_slots(
        self, provider_id: str, limit: int = 15
    ) -> List[AppointmentSlot]: ...

    async def create_booking(
        self, user_id: int, slot_id: str
    ) -> Booking: ...

    async def add_to_waitlist(
        self, user_id: int, provider_id: str
    ) -> None: ...

    async def get_provider_id_by_slot(
        self, slot_id: str
    ) -> Optional[str]: ...


class UserServiceProtocol(Protocol):
    """Contrato para el servicio de usuarios."""

    async def get_user(
        self, user_id: int
    ) -> Optional[TelegramUser]: ...

    async def upsert_user(
        self, user: TelegramUser
    ) -> tuple[TelegramUser, bool]: ...

    async def update_field(
        self, user_id: int, field: str, value: str
    ) -> bool: ...

    async def get_reminder_preferences(
        self, user_id: int
    ) -> ReminderPreferences: ...

    async def update_reminder_preference(
        self, user_id: int, field: str
    ) -> ReminderPreferences: ...


class AIServiceProtocol(Protocol):
    """Contrato para el servicio de IA (LLM)."""

    async def get_response(
        self, user_text: str, context: Optional[str] = None
    ) -> str: ...


class RAGServiceProtocol(Protocol):
    """
    Contrato para el servicio de RAG (Retrieval Augmented Generation).

    Nota: El tipo de retorno de ``search()`` es ``list[Any]`` porque
    ``KBEntry`` es un tipo local del módulo ``rag_service``.  En una
    futura iteración, ``KBEntry`` debería moverse a
    ``app/domain/entities.py``.
    """

    async def search(
        self,
        text: str,
        provider_id: Optional[str] = None,
        limit: int = 3,
    ) -> list[Any]: ...

    @staticmethod
    def format_context(entries: list) -> str:
        """Formatea las entradas de la KB en un bloque de contexto para el LLM."""
        ...


class NotificationServiceProtocol(Protocol):
    """Contrato para el servicio de notificaciones y crons."""

    async def send_reminders(self) -> None: ...

    async def auto_cancel_expired_bookings(self) -> None: ...


class GCalServiceProtocol(Protocol):
    """Contrato para el servicio de sincronización de Google Calendar."""

    async def sync_booking_to_gcal(self, booking_id: int) -> None: ...

    async def delete_gcal_event(self, booking_id: int) -> None: ...

    async def reconcile_all(
        self, max_retries: int = 5, batch_size: int = 20
    ) -> dict[str, Any]: ...


class SlotEngineProtocol(Protocol):
    """Contrato para el motor de generación/proyección de slots."""

    async def generate_slots_for_all_providers(
        self, days: int = 60
    ) -> None: ...

    async def generate_slots_for_provider(
        self, provider_id: str, days: int = 60
    ) -> None: ...


# ═══════════════════════════════════════════════════════════════════════════
# CAPA TELEGRAM
# ═══════════════════════════════════════════════════════════════════════════


@runtime_checkable
class TelegramSenderProtocol(Protocol):
    """
    Contrato para el emisor de mensajes a Telegram.

    ``send_message`` inserta en la tabla outbox (transaccional).
    ``flush_outbox`` envía los mensajes pendientes vía HTTP.
    ``build_inline_keyboard`` / ``build_paginated_keyboard`` son
    funciones puras sin estado; se definen como métodos regulares
    en el protocolo para que los consumidores las invoquen sobre
    la instancia.  La implementación puede mantenerlas como
    ``@staticmethod``.
    """

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    async def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> None: ...

    async def send_document(
        self,
        chat_id: int,
        document: bytes,
        filename: str,
        caption: Optional[str] = None,
    ) -> None: ...

    async def flush_outbox(self, chat_id: int) -> None: ...

    def build_inline_keyboard(
        self,
        options: List[str],
        version: int,
        include_nav: bool = False,
    ) -> Dict[str, Any]: ...

    def build_paginated_keyboard(
        self,
        options: List[str],
        version: int,
        start_idx: int,
        page: int,
        total_pages: int,
        include_nav: bool = False,
    ) -> Dict[str, Any]: ...


# ═══════════════════════════════════════════════════════════════════════════
# CAPA FSM
# ═══════════════════════════════════════════════════════════════════════════


class FSMRouterProtocol(Protocol):
    """
    Contrato para el router de la máquina de estados finitos.

    Recibe el estado actual y el texto del usuario, ejecuta el
    handler correspondiente y muta el estado in-place.
    """

    async def route(
        self, state: ConversationState, text: str
    ) -> None: ...
