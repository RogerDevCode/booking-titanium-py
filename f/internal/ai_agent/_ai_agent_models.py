from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# AI AGENT — Data Models (v4.0)
# ============================================================================


# ── Conversation State (input context)
class ConversationState(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    previous_intent: str | None = None
    active_flow: Literal[
        "booking_wizard",
        "reschedule_flow",
        "cancellation_flow",
        "reminder_flow",
        "selecting_specialty",
        "selecting_datetime",
        "booking",
        "none",
    ] = "none"
    flow_step: int = Field(default=0, ge=0)
    pending_data: dict[str, Any] = Field(default_factory=dict)
    last_user_utterance: str | None = None
    booking_state_name: str = "idle"
    session_id: str | None = None


# ── User Profile
class UserProfile(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    is_first_time: bool
    booking_count: int = Field(ge=0)


# ── Input
class AIAgentInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    chat_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=500)
    provider_id: str | None = None
    conversation_state: ConversationState | None = None
    user_profile: UserProfile | None = None
    pg_url: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None


# ── Entities
class EntityMap(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    date: str | None = None
    time: str | None = None
    provider_name: str | None = None
    provider_id: str | None = None
    service_type: str | None = None
    service_id: str | None = None
    booking_id: str | None = None
    channel: str | None = None
    reminder_window: str | None = None


# ── Context
class AvailabilityContext(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    is_today: bool
    is_tomorrow: bool
    is_urgent: bool
    is_flexible: bool
    is_specific_date: bool
    time_preference: Literal["morning", "afternoon", "evening", "any"]
    day_preference: str | None = None


class ContextAdjustment(TypedDict):
    adjusted: bool
    intent: str
    confidence: float
    reason: str


# ── Enums for Logic
SocialSubtype = Literal["saludo", "despedida", "agradecimiento"]
ReminderSubtype = Literal["activar", "desactivar", "preferencias"]
NavSubtype = Literal["menu", "siguiente", "atras", "confirmar"]
DialogueAct = Literal["inform", "question", "request_action", "confirm", "acknowledge", "offer", "close"]
UIComponent = Literal[
    "text_message", "quick_replies", "form_card", "list_card", "confirmation_card", "warning_card", "menu_card"
]
EscalationLevel = Literal["none", "priority_queue", "human_handoff", "medical_emergency"]


# ── Final Intent Result
class IntentResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    intent: str  # Validated against INTENT list in logic
    confidence: float = Field(ge=0.0, le=1.0)
    entities: EntityMap
    context: AvailabilityContext
    subtype: SocialSubtype | ReminderSubtype | NavSubtype | None = None
    dialogue_act: DialogueAct = "inform"
    ui_component: UIComponent = "text_message"
    needs_more_info: bool = False
    follow_up: str | None = None
    ai_response: str = Field(min_length=1)
    requires_human: bool = False
    escalation_level: EscalationLevel = "none"
    cot_reasoning: str = Field(min_length=1)
    validation_passed: bool
    validation_errors: list[str] = Field(default_factory=list)
    requires_fsm_routing: bool = False


# ── Internal Support Models
class LLMOutputEntities(BaseModel):
    date: str | None = None
    time: str | None = None
    booking_id: str | None = None
    client_name: str | None = None
    service_type: str | None = None


class LLMOutput(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    intent: str
    confidence: float
    entities: LLMOutputEntities | None = None
    needs_more: bool = False
    follow_up: str | None = None
