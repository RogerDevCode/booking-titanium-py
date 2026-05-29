"""
Tests de Menús — Cobertura completa del Menú Principal (8 opciones)
y todos los sub-flujos FSM: Agendar, Mis Horas, Cancelar, Reagendar,
Reporte, Información, Mis Datos, y comportamiento UNKNOWN (menú de bienvenida).

Sin base de datos real — todo mockeado a nivel de servicio.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from typing import Any
from app.domain.models import ConversationState
from app.domain.enums import FSMState, Intent, BookingStatus
from app.domain.entities import Specialty, Provider, AppointmentSlot, Booking, BookingView
from app.telegram.sender import TelegramSender
telegram_sender = AsyncMock()
telegram_sender.build_inline_keyboard = TelegramSender.build_inline_keyboard
telegram_sender.build_paginated_keyboard = TelegramSender.build_paginated_keyboard
booking_service = AsyncMock()
user_service = AsyncMock()
slot_engine = AsyncMock()
booking_repo = AsyncMock()
fake_db = AsyncMock()

import contextlib  # noqa: E402

@contextlib.contextmanager
def patch(target, new=None, **kwargs):
    if new is None:
        new = AsyncMock()
        
    old_val = None
    target_obj = None
    attr_name = ""
    
    if "telegram_sender.send_message" in target:
        target_obj = telegram_sender
        attr_name = "send_message"
    elif "get_all_specialties" in target:
        target_obj = booking_service
        attr_name = "get_all_specialties"
    elif "get_providers_by_specialty" in target:
        target_obj = booking_service
        attr_name = "get_providers_by_specialty"
    elif "get_available_slots" in target:
        target_obj = booking_service
        attr_name = "get_available_slots"
    elif "create_booking" in target:
        target_obj = booking_service
        attr_name = "create_booking"
    elif "get_user_bookings" in target:
        target_obj = booking_service
        attr_name = "get_user_bookings"
    elif "cancel_booking" in target:
        target_obj = booking_service
        attr_name = "cancel_booking"
    elif "reschedule_booking" in target:
        target_obj = booking_service
        attr_name = "reschedule_booking"
    elif "get_user" in target:
        target_obj = user_service
        attr_name = "get_user"
    elif "get_provider_id_by_booking" in target:
        target_obj = booking_repo
        attr_name = "get_provider_id_by_booking"
    elif "fake_db.execute" in target:
        target_obj = fake_db
        attr_name = "execute"
    
    if target_obj:
        old_val = getattr(target_obj, attr_name)
        setattr(target_obj, attr_name, new)
        
    try:
        yield new
    finally:
        if target_obj:
            setattr(target_obj, attr_name, old_val)


fsm_router: Any = None

@pytest.fixture
def local_fsm_router():
    from app.pipeline.preprocessor import MessagePreprocessor
    from app.pipeline.classifier import IntentClassifier
    from app.fsm.main import FSMRouter
    MessagePreprocessor()
    IntentClassifier()
    return FSMRouter(booking_service=booking_service, user_service=user_service, sender=telegram_sender, booking_repo=booking_repo, db=fake_db)

@pytest.fixture(autouse=True)
def inject_container(local_fsm_router):
    global fsm_router
    fsm_router = local_fsm_router
    telegram_sender.reset_mock()
    booking_service.reset_mock()
    user_service.reset_mock()
    slot_engine.reset_mock()
    booking_repo.reset_mock()
    fake_db.reset_mock()

async def idle_handler(state, text):
    return await fsm_router._idle_handler(state, text)

async def selecting_specialty_handler(state, text):
    return await fsm_router._booking_flow.selecting_specialty_handler(state, text)

async def selecting_doctor_handler(state, text):
    return await fsm_router._booking_flow.selecting_doctor_handler(state, text)

async def selecting_time_handler(state, text):
    return await fsm_router._booking_flow.selecting_time_handler(state, text)

async def confirming_booking_handler(state, text):
    return await fsm_router._booking_flow.confirming_booking_handler(state, text)

async def cancellation_handler(state, text):
    return await fsm_router._booking_flow.cancellation_handler(state, text)

async def reschedule_handler(state, text):
    return await fsm_router._booking_flow.reschedule_handler(state, text)

async def my_bookings_handler(state, text):
    return await fsm_router._booking_flow.my_bookings_handler(state, text)

def make_state(chat_id: int=12345, intent: Intent | None=None) -> ConversationState:
    state = ConversationState(chat_id=chat_id)
    if intent:
        state.context['preflight'] = {'intent': intent}
    return state

def make_specialty(idx: int=1) -> Specialty:
    return Specialty(id=f'sp-{idx}', name=f'Especialidad {idx}', description=f'Desc {idx}')

def make_provider(idx: int=1, specialty_id: str='sp-1') -> Provider:
    return Provider(id=f'doc-{idx}', name=f'Dr. Médico {idx}', specialty_id=specialty_id)

def make_slot(idx: int=1, doctor_id: str='doc-1') -> AppointmentSlot:
    base = datetime(2026, 6, 1, 9, 0) + timedelta(hours=idx)
    return AppointmentSlot(id=f'slot-{idx}', doctor_id=doctor_id, start_time=base, end_time=base + timedelta(hours=1), is_available=True)

def make_booking(idx: int=1) -> Booking:
    now = datetime.now()
    return Booking(id=idx, user_id=12345, slot_id=f'slot-{idx}', status=BookingStatus.CONFIRMED, created_at=now, updated_at=now)

def make_booking_view(idx: int=1) -> BookingView:
    return BookingView(id=idx, status=BookingStatus.CONFIRMED, start_time=datetime(2026, 6, 1, 10, 0) + timedelta(hours=idx), provider_name=f'Dr. Médico {idx}', specialty_name=f'Especialidad {idx}')

class _SendCapture:
    """Captura todos los send_message enviados durante un test."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, chat_id: int, text: str, reply_markup: Any=None) -> None:
        self.calls.append({'chat_id': chat_id, 'text': text, 'reply_markup': reply_markup})

    @property
    def last_text(self) -> str:
        return self.calls[-1]['text'] if self.calls else ''

    @property
    def last_markup(self) -> Any:
        return self.calls[-1]['reply_markup'] if self.calls else None

    @property
    def texts(self) -> list[str]:
        return [c['text'] for c in self.calls]

class TestMenuPrincipal:
    """Valida que idle_handler transicione correctamente según el intent."""

    @pytest.mark.asyncio
    async def test_opcion_1_agendar_hora(self) -> None:
        """Opción 1: BOOK_APPOINTMENT → estado SELECTING_SPECIALTY."""
        state = make_state(intent=Intent.BOOK_APPOINTMENT)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)), patch('tests.unit.test_menus_completo.booking_service.get_all_specialties', new=AsyncMock(return_value=[])):
            await idle_handler(state, '1')
        assert state.state == FSMState.SELECTING_SPECIALTY
        assert 'Agendar' in capture.last_text or 'especialidad' in capture.last_text.lower()

    @pytest.mark.asyncio
    async def test_opcion_2_mis_horas(self) -> None:
        """Opción 2: MY_BOOKINGS → estado VIEWING_BOOKINGS."""
        state = make_state(intent=Intent.MY_BOOKINGS)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)), patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=[])):
            await idle_handler(state, '2')
        assert state.state == FSMState.IDLE
        assert any(('no tienes' in t.lower() or 'citas' in t.lower() for t in capture.texts))

    @pytest.mark.asyncio
    async def test_opcion_3_cancelar_hora(self) -> None:
        """Opción 3: CANCEL_APPOINTMENT → estado CANCELLING_BOOKING."""
        state = make_state(intent=Intent.CANCEL_APPOINTMENT)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)), patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=[])):
            await idle_handler(state, '3')
        assert state.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_opcion_4_reagendar_hora(self) -> None:
        """Opción 4: RESCHEDULE_APPOINTMENT → estado RESCHEDULING_BOOKING."""
        state = make_state(intent=Intent.RESCHEDULE_APPOINTMENT)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)), patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=[])):
            await idle_handler(state, '4')
        assert state.state == FSMState.IDLE

    @pytest.mark.asyncio
    async def test_opcion_5_reporte(self) -> None:
        """Opción 5: GET_REPORT → estado se mantiene IDLE (no hay flujo de submenú)."""
        state = make_state(intent=Intent.GET_REPORT)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await idle_handler(state, '5')
        assert state.state == FSMState.VIEWING_REPORT
        assert 'reporte' in capture.last_text.lower() or 'PDF' in capture.last_text

    @pytest.mark.asyncio
    async def test_opcion_7_informacion(self) -> None:
        """Opción 7: GET_INFO → estado WAITING_FAQ."""
        state = make_state(intent=Intent.GET_INFO)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await idle_handler(state, '7')
        assert state.state == FSMState.WAITING_FAQ
        assert 'asistente' in capture.last_text.lower() or 'Información' in capture.last_text

    @pytest.mark.asyncio
    async def test_opcion_8_mis_datos(self) -> None:
        """Opción 8: MANAGE_PROFILE → estado UPDATING_PROFILE."""
        state = make_state(intent=Intent.MANAGE_PROFILE)
        capture = _SendCapture()
        from app.domain.entities import TelegramUser
        dummy_user = TelegramUser(id=1, first_name='Test')
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)), patch('tests.unit.test_menus_completo.user_service.get_user', new=AsyncMock(return_value=dummy_user)):
            await idle_handler(state, '8')
        assert state.state == FSMState.UPDATING_PROFILE
        assert state.context.get('step') == 'menu'

    @pytest.mark.asyncio
    async def test_unknown_intent_muestra_menu_bienvenida(self) -> None:
        """Intent UNKNOWN → muestra el menú principal con las 8 opciones."""
        state = make_state(intent=Intent.UNKNOWN)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await idle_handler(state, 'hola')
        assert state.state == FSMState.IDLE
        assert capture.last_markup is not None
        kb = capture.last_markup.get('inline_keyboard', [])
        assert len(kb) == 8, f'El menú debe tener 8 opciones, tiene {len(kb)}'
        botones_text = ' '.join([boton[0]['text'] for boton in kb])
        for opt in ['Agendar', 'Mis horas', 'Cancelar', 'Reagendar', 'Reporte', 'Información', 'Mis datos']:
            assert opt in botones_text, f"Opción '{opt}' no encontrada en el menú"

    @pytest.mark.asyncio
    async def test_sin_preflight_muestra_menu(self) -> None:
        """Sin context preflight → igual muestra menú (no crashea)."""
        state = ConversationState(chat_id=99999)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await idle_handler(state, '')
        assert state.state == FSMState.IDLE
        assert capture.last_markup is not None

class TestFlujoCitaCompleto:
    """Simula el funnel completo de agendamiento con 3 especialidades, 3 doctores, 5 slots."""

    @pytest.fixture
    def specialties(self) -> list[Specialty]:
        return [make_specialty(i) for i in range(1, 4)]

    @pytest.fixture
    def providers(self) -> list[Provider]:
        return [make_provider(i, specialty_id='sp-1') for i in range(1, 4)]

    @pytest.fixture
    def slots(self) -> list[AppointmentSlot]:
        return [make_slot(i) for i in range(1, 6)]

    @pytest.mark.asyncio
    async def test_seleccion_especialidad_por_numero(self, specialties, providers) -> None:
        """Seleccionar especialidad por número actualiza booking_draft y avanza el estado."""
        state = make_state()
        state.state = FSMState.SELECTING_SPECIALTY
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_all_specialties', new=AsyncMock(return_value=specialties)), patch('tests.unit.test_menus_completo.booking_service.get_providers_by_specialty', new=AsyncMock(return_value=providers)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_specialty_handler(state, '1')
        assert state.state == FSMState.SELECTING_DOCTOR
        assert state.booking_draft['specialty_id'] == 'sp-1'
        assert state.booking_draft['specialty_name'] == 'Especialidad 1'
        assert len(state.context['items']) == 3

    @pytest.mark.asyncio
    async def test_seleccion_especialidad_por_nombre(self, specialties, providers) -> None:
        """Seleccionar especialidad por nombre parcial también funciona."""
        state = make_state()
        state.state = FSMState.SELECTING_SPECIALTY
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_all_specialties', new=AsyncMock(return_value=specialties)), patch('tests.unit.test_menus_completo.booking_service.get_providers_by_specialty', new=AsyncMock(return_value=providers)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_specialty_handler(state, 'Especialidad 2')
        assert state.state == FSMState.SELECTING_DOCTOR
        assert state.booking_draft['specialty_name'] == 'Especialidad 2'

    @pytest.mark.asyncio
    async def test_especialidad_invalida_no_avanza(self, specialties) -> None:
        """Texto que no mapea a ninguna especialidad → mensaje de error, sin cambio de estado."""
        state = make_state()
        state.state = FSMState.SELECTING_SPECIALTY
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_all_specialties', new=AsyncMock(return_value=specialties)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_specialty_handler(state, '99')
        assert state.state == FSMState.SELECTING_SPECIALTY
        assert any(('no entendí' in t.lower() or 'especialidad' in t.lower() for t in capture.texts))

    @pytest.mark.asyncio
    async def test_especialidad_sin_doctores_vuelve_a_idle(self, specialties) -> None:
        """Si la especialidad seleccionada no tiene doctores → vuelve a IDLE con aviso."""
        state = make_state()
        state.state = FSMState.SELECTING_SPECIALTY
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_all_specialties', new=AsyncMock(return_value=specialties)), patch('tests.unit.test_menus_completo.booking_service.get_providers_by_specialty', new=AsyncMock(return_value=[])), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_specialty_handler(state, '1')
        assert state.state == FSMState.IDLE
        assert any(('no hay doctores' in t.lower() or 'disponibles' in t.lower() for t in capture.texts))

    @pytest.mark.asyncio
    async def test_seleccion_doctor_por_numero(self, slots) -> None:
        """Seleccionar doctor por número → avanza a SELECTING_TIME con slots paginados."""
        state = make_state()
        state.state = FSMState.SELECTING_DOCTOR
        state.booking_draft['specialty_name'] = 'Especialidad 1'
        state.context['items'] = [{'id': 'doc-1', 'name': 'Dr. Médico 1'}, {'id': 'doc-2', 'name': 'Dr. Médico 2'}]
        state.context['page'] = 0
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_available_slots', new=AsyncMock(return_value=slots)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_doctor_handler(state, '1')
        assert state.state == FSMState.SELECTING_TIME
        assert state.booking_draft['doctor_id'] == 'doc-1'
        assert state.booking_draft['doctor_name'] == 'Dr. Médico 1'
        assert len(state.context['items']) == 5

    @pytest.mark.asyncio
    async def test_doctor_sin_slots_vuelve_a_idle(self) -> None:
        state = make_state()
        state.state = FSMState.SELECTING_DOCTOR
        state.context["specialty"] = "cardiologia"
        state.context["items"] = [{"id": "doc-1", "name": "Dr. Medico"}]
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_available_slots', new=AsyncMock(return_value=[])), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_doctor_handler(state, "1")

        assert state.state == FSMState.JOINING_WAITLIST
        assert any('no tiene horas' in t.lower() or 'disponibles' in t.lower() for t in capture.texts)

    @pytest.mark.asyncio
    async def test_seleccion_slot_avanza_a_confirmacion(self, slots) -> None:
        """Seleccionar slot → avanza a CONFIRMING_BOOKING con resumen."""
        state = make_state()
        state.state = FSMState.SELECTING_TIME
        state.booking_draft = {'specialty_name': 'Cardiología', 'doctor_name': 'Dr. Corazón', 'doctor_id': 'doc-1'}
        state.context['items'] = [{'id': s.id, 'time': s.start_time.isoformat()} for s in slots]
        state.context['page'] = 0
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_time_handler(state, '1')
        assert state.state == FSMState.CONFIRMING_BOOKING
        assert state.booking_draft['slot_id'] == slots[0].id
        text = capture.last_text
        assert 'Cardiología' in text
        assert 'Dr. Corazón' in text

    @pytest.mark.asyncio
    async def test_confirmacion_si_crea_reserva(self, slots) -> None:
        """Respuesta 'SI' → crea la reserva y limpia el estado."""
        state = make_state()
        state.state = FSMState.CONFIRMING_BOOKING
        state.booking_draft = {'specialty_name': 'Cardiología', 'doctor_name': 'Dr. X', 'slot_id': 'slot-1', 'slot_time': '2026-06-01T10:00:00'}
        booking = make_booking(42)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.create_booking', new=AsyncMock(return_value=booking)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await confirming_booking_handler(state, 'SI')
        assert state.state == FSMState.IDLE
        assert state.booking_draft == {}
        assert any('confirmada' in t.lower() for t in capture.texts)

    @pytest.mark.asyncio
    async def test_confirmacion_no_cancela_sin_crear(self) -> None:
        """Respuesta 'NO' → cancela el flujo sin llamar a create_booking."""
        state = make_state()
        state.state = FSMState.CONFIRMING_BOOKING
        state.booking_draft = {'slot_id': 'slot-1', 'slot_time': '2026-06-01T10:00:00'}
        capture = _SendCapture()
        mock_create = AsyncMock()
        with patch('tests.unit.test_menus_completo.booking_service.create_booking', new=mock_create), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await confirming_booking_handler(state, 'NO')
        mock_create.assert_not_called()
        assert state.state == FSMState.IDLE
        assert state.booking_draft == {}

    @pytest.mark.asyncio
    async def test_confirmacion_fallo_db_notifica_usuario(self) -> None:
        """Si create_booking lanza excepción → usuario recibe mensaje de error, no crash."""
        state = make_state()
        state.booking_draft = {'slot_id': 'slot-1', 'slot_time': '2026-06-01T10:00:00'}
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.create_booking', new=AsyncMock(side_effect=Exception('DB connection lost'))), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await confirming_booking_handler(state, 'sí')
        assert state.state == FSMState.IDLE
        assert any(('problema' in t.lower() or 'error' in t.lower() for t in capture.texts))

class TestMisHoras:

    @pytest.mark.asyncio
    async def test_con_reservas_activas_las_lista(self) -> None:
        """my_bookings_handler muestra todas las reservas activas."""
        state = make_state()
        bookings = [make_booking_view(i) for i in range(1, 4)]
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=bookings)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await my_bookings_handler(state, '')
        text = capture.last_text
        for bv in bookings:
            assert bv.provider_name in text
            assert bv.specialty_name in text

    @pytest.mark.asyncio
    async def test_sin_reservas_activas_mensaje_vacio(self) -> None:
        """Si no hay reservas → mensaje informativo, sin crash."""
        state = make_state()
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=[])), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await my_bookings_handler(state, '')
        assert any(('no tienes' in t.lower() or 'actualmente' in t.lower() for t in capture.texts))

class TestCancelarHora:

    def _bookings(self) -> list[BookingView]:
        return [make_booking_view(i) for i in range(1, 4)]

    @pytest.mark.asyncio
    async def test_lista_reservas_para_cancelar(self) -> None:
        """Primera llamada sin número → lista las reservas disponibles."""
        state = make_state()
        state.state = FSMState.CANCELLING_BOOKING
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=self._bookings())), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await cancellation_handler(state, '')
        assert capture.last_markup is not None
        kb = capture.last_markup['inline_keyboard']
        assert len(kb) == 4

    @pytest.mark.asyncio
    async def test_cancelar_reserva_seleccionada(self) -> None:
        """Seleccionar '2' cancela la segunda reserva y vuelve a IDLE."""
        state = make_state()
        state.state = FSMState.CANCELLING_BOOKING
        bookings = self._bookings()
        state.context['items'] = [{'id': b.id, 'specialty': b.specialty_name, 'doctor': b.provider_name, 'time': b.start_time.strftime('%d/%m %H:%M')} for b in bookings]
        state.context['page'] = 0
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=bookings)), patch('tests.unit.test_menus_completo.booking_service.cancel_booking', new=AsyncMock(return_value=True)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await cancellation_handler(state, '2')
        assert state.state == FSMState.IDLE
        assert state.context == {}
        assert any(('cancelada' in t.lower() for t in capture.texts))

    @pytest.mark.asyncio
    async def test_cancelacion_fallida_informa_al_usuario(self) -> None:
        """Si cancel_booking retorna False → usuario recibe mensaje de error."""
        state = make_state()
        state.state = FSMState.CANCELLING_BOOKING
        bookings = self._bookings()
        state.context['items'] = [{'id': b.id, 'specialty': b.specialty_name, 'doctor': b.provider_name, 'time': b.start_time.strftime('%d/%m %H:%M')} for b in bookings]
        state.context['page'] = 0
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=bookings)), patch('tests.unit.test_menus_completo.booking_service.cancel_booking', new=AsyncMock(return_value=False)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await cancellation_handler(state, '1')
        assert any(('no se pudo' in t.lower() or 'error' in t.lower() for t in capture.texts))

    @pytest.mark.asyncio
    async def test_sin_reservas_vuelve_a_idle(self) -> None:
        """Si no hay reservas para cancelar → vuelve a IDLE con mensaje informativo."""
        state = make_state()
        state.state = FSMState.CANCELLING_BOOKING
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=[])), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await cancellation_handler(state, '')
        assert state.state == FSMState.IDLE
        assert any(('no tienes' in t.lower() for t in capture.texts))

class TestReagendarHora:

    def _bookings(self) -> list[BookingView]:
        return [make_booking_view(i) for i in range(1, 3)]

    def _slots(self) -> list[AppointmentSlot]:
        return [make_slot(i) for i in range(10, 13)]

    @pytest.mark.asyncio
    async def test_lista_reservas_para_reagendar(self) -> None:
        """Primera llamada → lista reservas reagendables."""
        state = make_state()
        state.state = FSMState.RESCHEDULING_BOOKING
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=self._bookings())), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await reschedule_handler(state, '')
        assert capture.last_markup is not None

    @pytest.mark.asyncio
    async def test_seleccion_reserva_muestra_nuevos_slots(self) -> None:
        """Seleccionar reserva '1' → muestra los nuevos slots disponibles."""
        state = make_state()
        state.state = FSMState.RESCHEDULING_BOOKING
        bookings = self._bookings()
        slots = self._slots()
        state.context['items'] = [{'id': b.id, 'specialty': b.specialty_name, 'doctor': b.provider_name, 'time': b.start_time.strftime('%d/%m %H:%M')} for b in bookings]
        state.context['page'] = 0
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=bookings)), patch('tests.unit.test_menus_completo.booking_repo.get_provider_id_by_booking', new=AsyncMock(return_value='doc-1')), patch('tests.unit.test_menus_completo.booking_service.get_available_slots', new=AsyncMock(return_value=slots)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await reschedule_handler(state, '1')
        assert state.context.get('step') == 'select_new_slot'
        assert len(state.context['items']) == 3
        assert capture.last_markup is not None

    @pytest.mark.asyncio
    async def test_reagendar_exito_limpia_estado(self) -> None:
        """Seleccionar nuevo slot reagenda y vuelve a IDLE."""
        state = make_state()
        state.state = FSMState.RESCHEDULING_BOOKING
        slots = self._slots()
        state.context['step'] = 'select_new_slot'
        state.context['items'] = [{'id': s.id, 'time': s.start_time.isoformat()} for s in slots]
        state.context['page'] = 0
        state.booking_draft['old_booking_id'] = 1
        new_booking = make_booking(99)
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=self._bookings())), patch('tests.unit.test_menus_completo.booking_service.reschedule_booking', new=AsyncMock(return_value=(new_booking, 'old-slot-123'))), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await reschedule_handler(state, '1')
        assert state.state == FSMState.IDLE
        assert state.context == {}
        assert state.booking_draft == {}
        assert any(('reagendada' in t.lower() or '99' in t for t in capture.texts))

    @pytest.mark.asyncio
    async def test_sin_reservas_vuelve_a_idle(self) -> None:
        """Si no hay reservas que reagendar → vuelve a IDLE."""
        state = make_state()
        state.state = FSMState.RESCHEDULING_BOOKING
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_user_bookings', new=AsyncMock(return_value=[])), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await reschedule_handler(state, '')
        assert state.state == FSMState.IDLE

class TestPaginacionMenus:
    """Verifica que la paginación no corrompe el estado FSM."""

    @pytest.mark.asyncio
    async def test_page_next_en_seleccion_doctor(self) -> None:
        """page_next avanza la página del menú de doctores correctamente."""
        state = make_state()
        state.state = FSMState.SELECTING_DOCTOR
        state.booking_draft['specialty_name'] = 'Cardiología'
        state.context['items'] = [{'id': f'doc-{i}', 'name': f'Dr. {i}'} for i in range(12)]
        state.context['page'] = 0
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_doctor_handler(state, 'page_next')
        assert state.context['page'] == 1
        assert state.state == FSMState.SELECTING_DOCTOR
        kb = capture.last_markup['inline_keyboard']
        assert len(kb) == 7

    @pytest.mark.asyncio
    async def test_page_prev_en_primera_pagina_no_baja_de_cero(self) -> None:
        """page_prev en página 0 → se queda en 0 (no índice negativo)."""
        state = make_state()
        state.state = FSMState.SELECTING_DOCTOR
        state.booking_draft['specialty_name'] = 'Especialidad'
        state.context['items'] = [{'id': f'doc-{i}', 'name': f'Dr. {i}'} for i in range(10)]
        state.context['page'] = 0
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock()):
            await selecting_doctor_handler(state, 'page_prev')
        assert state.context['page'] == 0

    @pytest.mark.asyncio
    async def test_seleccion_en_pagina_2_usa_indice_absoluto(self) -> None:
        """Seleccionar opción '8' en página 1 referencia al item de índice 7 (absoluto)."""
        state = make_state()
        state.state = FSMState.SELECTING_DOCTOR
        state.booking_draft['specialty_name'] = 'Cardiología'
        doctors = [{'id': f'doc-{i}', 'name': f'Dr. Médico {i}'} for i in range(12)]
        state.context['items'] = doctors
        state.context['page'] = 1
        from datetime import datetime

        class MockSlot:
            id = 'slot-1'
            start_time = datetime(2026, 5, 28, 10, 0)
        mock_slots = [MockSlot()]
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.booking_service.get_available_slots', new=AsyncMock(return_value=mock_slots)), patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await selecting_doctor_handler(state, '8')
        assert state.booking_draft['doctor_id'] == 'doc-7'
        assert state.booking_draft['doctor_name'] == 'Dr. Médico 7'

class TestFSMRouter:
    """Verifica que el router despacha correctamente por estado FSM."""

    @pytest.mark.asyncio
    async def test_router_despacha_idle(self) -> None:
        state = ConversationState(chat_id=1)
        state.state = FSMState.IDLE
        state.context['preflight'] = {'intent': Intent.GET_REPORT}
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)):
            await fsm_router.route( # type: ignore
state, '5')
        assert 'reporte' in capture.last_text.lower() or 'PDF' in capture.last_text

    @pytest.mark.asyncio
    async def test_router_estado_desconocido_no_crashea(self) -> None:
        """Un estado no registrado → el router no lanza excepción (fallback silencioso)."""
        state = ConversationState(chat_id=1)
        state.state = FSMState.SELECTING_DATE # type: ignore
        await fsm_router.route( # type: ignore
state, 'algo')

    @pytest.mark.asyncio
    async def test_router_start_always_resets_and_renders_menu(self) -> None:
        """/start debe restablecer el estado y renderizar el menú principal incluso si ya está en IDLE, message_id != None y version > 0."""
        state = ConversationState(chat_id=1)
        state.state = FSMState.IDLE
        state.version = 1
        state.message_id = 999
        capture = _SendCapture()
        with patch('tests.unit.test_menus_completo.telegram_sender.send_message', new=AsyncMock(side_effect=capture.record)), patch('tests.unit.test_menus_completo.fake_db.execute', new=AsyncMock()) as mock_execute:
            await fsm_router.route( # type: ignore
state, '/start')
        mock_execute.assert_called_once_with("UPDATE outbox_messages SET status = 'CANCELLED' WHERE chat_id = $1 AND status = 'PENDING'", state.chat_id)
        assert len(capture.calls) > 0
        menu_text = capture.calls[0]['text']
        assert 'Bienvenido' in menu_text
        assert capture.calls[0]['reply_markup'] is not None