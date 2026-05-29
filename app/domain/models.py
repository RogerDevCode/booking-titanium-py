from datetime import datetime
from typing import Optional, List, Literal, Dict, Any, Set
from pydantic import BaseModel, Field, ConfigDict
from app.domain.enums import BookingStatus, FSMState
from app.core.logging import logger

from dataclasses import dataclass, field

class FSMTransitionError(Exception):
    pass

FSM_TRANSITIONS: Dict[FSMState, Set[FSMState]] = {
    FSMState.IDLE: {
        FSMState.SELECTING_SPECIALTY,
        FSMState.VIEWING_BOOKINGS,
        FSMState.CANCELLING_BOOKING,
        FSMState.RESCHEDULING_BOOKING,
        FSMState.WAITING_FAQ,
        FSMState.UPDATING_PROFILE,
        FSMState.VIEWING_REPORT
    },
    FSMState.SELECTING_SPECIALTY: {
        FSMState.IDLE,
        FSMState.SELECTING_DOCTOR
    },
    FSMState.SELECTING_DOCTOR: {
        FSMState.IDLE,
        FSMState.SELECTING_SPECIALTY,
        FSMState.SELECTING_TIME
    },
    FSMState.SELECTING_TIME: {
        FSMState.IDLE,
        FSMState.SELECTING_DOCTOR,
        FSMState.CONFIRMING_BOOKING
    },
    FSMState.CONFIRMING_BOOKING: {
        FSMState.IDLE,
        FSMState.SELECTING_TIME
    },
    FSMState.VIEWING_BOOKINGS: {
        FSMState.IDLE,
        FSMState.CANCELLING_BOOKING,
        FSMState.RESCHEDULING_BOOKING
    },
    FSMState.CANCELLING_BOOKING: {
        FSMState.IDLE
    },
    FSMState.RESCHEDULING_BOOKING: {
        FSMState.IDLE,
        FSMState.SELECTING_TIME
    },
    FSMState.WAITING_FAQ: {
        FSMState.IDLE
    },
    FSMState.UPDATING_PROFILE: {
        FSMState.IDLE
    },
    FSMState.VIEWING_REPORT: {
        FSMState.IDLE
    }
}

@dataclass(slots=True)
class ConversationState:
    chat_id: int
    state: FSMState = FSMState.IDLE
    active_flow: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    booking_draft: Dict[str, Any] = field(default_factory=dict)
    message_id: Optional[int] = None
    version: int = 0
    updated_at: datetime = field(default_factory=datetime.now)

    def transition_to(self, new_state: FSMState) -> None:
        if new_state == self.state:
            return
        allowed = FSM_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise FSMTransitionError(
                f"Transición inválida: {self.state.value} → {new_state.value}"
            )
        logger.info(
            "FSM state transition",
            chat_id=self.chat_id,
            old=self.state.value,
            new=new_state.value,
            version_before=self.version,
            version_after=self.version + 1,
        )
        self.state = new_state
        self.version += 1
        
        if new_state == FSMState.IDLE:
            self.context = {}
            self.booking_draft = {}
            self.active_flow = None

class BookingIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    user_id: int
    slot_id: str
    specialty: str
    doctor_id: str
    appointment_time: datetime



# --- Preprocessor Models ---

@dataclass(slots=True, frozen=True)
class SpellCorrection:
    original: str
    corrected: str

@dataclass(slots=True, frozen=True)
class ModismMatch:
    phrase: str
    canonical: str

@dataclass(slots=True, frozen=True)
class SecurityScanResult:
    threat_detected: bool = False
    threat_type: Literal["sql_injection", "xss", "command_injection", "prompt_injection", "none"] = "none"

@dataclass(slots=True, frozen=True)
class ExtractedEntities:
    urls: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    ruts: List[str] = field(default_factory=list)

@dataclass(slots=True, frozen=True)
class PreprocessorOutput:
    raw_text: str
    cleaned_text: str
    normalization_applied: bool
    spell_corrections: List[SpellCorrection]
    modism_matches: List[ModismMatch]
    confidence: float
    extracted_entities: ExtractedEntities
    security_scan: SecurityScanResult
