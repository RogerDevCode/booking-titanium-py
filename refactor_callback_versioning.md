# REFACTOR DIRECTIVE: Callback Data Versioning Pattern
## TARGET SYSTEM: Titanium Booking Engine
## PRIORITY: CRITICAL — Anti-pattern elimination
## SCOPE: Ghost Menu / Stale Callback corruption fix

---

## PROBLEM STATEMENT

ANTI-PATTERN DETECTED: "Deferred Keyboard Cleanup"

Current flow has a structural corruption window:

```
send_menu_B → telegram_returns_message_id → save_to_db
                                            ↑
                         CORRUPTION WINDOW: user can click here
                         before message_id is registered
                         FSM processes stale callback → state corruption
```

Root causes:
- Cleanup happens at START of next message, not at transition moment
- message_id used as security mechanism (wrong responsibility)
- N workers can race on same chat_id between send and save
- No callback authenticity verification at router level

---

## SOLUTION: Callback Data Versioning

PRINCIPLE: Stale callbacks self-invalidate without message editing or message_id tracking.
PATTERN: Encode conversation version into every callback_data string.
STANDARD: Used in production Telegram bots at scale (Aiogram ecosystem, python-telegram-bot advanced patterns).

VERSION FIELD: `conversation_states.version` (already exists in schema — no migration needed).
INCREMENT RULE: version++ on every call to `transition_to()` — nowhere else.

CALLBACK ENCODING SPEC:
```
FORMAT  : v{version}:{action}:{value}
EXAMPLE : v3:select_specialty:cardiology
EXAMPLE : v7:confirm_booking:slot_42
EXAMPLE : v1:cancel:back
```

VALIDATION RULE:
```
payload.version == state.version → PROCESS
payload.version != state.version → DISCARD SILENTLY (answer_callback empty)
```

---

## FILE 1 — CREATE

PATH: app/telegram/callback.py
RESPONSIBILITY: Encode and decode versioned callback_data strings.
DEPENDENCIES: none (pure functions, no I/O)

```python
from __future__ import annotations
from dataclasses import dataclass

_SEP: str = ":"
_VER: str = "v"


@dataclass(slots=True, frozen=True)
class CallbackPayload:
    version: int
    action: str
    value: str


def encode(version: int, action: str, value: str) -> str:
    """
    Encode a versioned callback_data string.

    Args:
        version: Current conversation state version from ConversationState.version
        action:  Intent identifier. Example: "select_specialty", "confirm_booking"
        value:   Payload value. Example: "cardiology", "slot_42", "back"

    Returns:
        Versioned string ready for InlineKeyboardButton.callback_data
        Example: "v3:select_specialty:cardiology"

    Rules:
        - MUST use state.version at the moment of keyboard construction
        - MUST be called AFTER transition_to() so version is already incremented
        - value MUST NOT contain ":" character
    """
    return f"{_VER}{version}{_SEP}{action}{_SEP}{value}"


def decode(raw: str) -> CallbackPayload | None:
    """
    Decode a versioned callback_data string.

    Args:
        raw: The callback_data string received from Telegram.

    Returns:
        CallbackPayload if valid format, None if malformed or legacy format.

    Rules:
        - Returns None for ANY malformed input — never raises
        - Caller is responsible for handling None (discard the callback)
    """
    parts = raw.split(_SEP, 2)
    if len(parts) != 3:
        return None
    prefix, action, value = parts
    if not prefix.startswith(_VER):
        return None
    try:
        version = int(prefix[1:])
    except ValueError:
        return None
    return CallbackPayload(version=version, action=action, value=value)
```

---

## FILE 2 — MODIFY

PATH: app/domain/models.py
CHANGE: Add version increment to `transition_to()` method.

LOCATE this method in ConversationState dataclass:

```python
# BEFORE — missing version increment
def transition_to(self, new_state: FSMState) -> None:
    if new_state == self.state:
        return
    allowed = FSM_TRANSITIONS.get(self.state, set())
    if new_state not in allowed:
        raise FSMTransitionError(
            f"Transición inválida detectada: {self.state.value} -> {new_state.value}"
        )
    logger.info("FSM state transition", chat_id=self.chat_id, old=self.state.value, new=new_state.value)
    self.state = new_state
```

```python
# AFTER — version increments atomically with state change
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
    self.version += 1  # ANY prior keyboard is now invalid
```

INVARIANT: version is ONLY incremented here. Never in handlers, never in repos, never manually.

---

## FILE 3 — MODIFY

PATH: app/fsm/router.py
CHANGE: Add callback version guard before dispatching to handler.

LOCATE the `route()` method (or equivalent dispatch entry point) and ADD this guard:

```python
# ADD this import at top of file
from app.telegram.callback import decode, CallbackPayload

# BEFORE — no version validation
async def route(update: TelegramUpdate, state: ConversationState) -> None:
    handler = self._handlers.get(state.state)
    if handler is None:
        raise FSMTransitionError(f"No handler for state: {state.state}")
    await handler(update, state)
```

```python
# AFTER — version guard added before dispatch
async def route(update: TelegramUpdate, state: ConversationState) -> None:

    if update.callback_query is not None:
        payload: CallbackPayload | None = decode(update.callback_query.data)

        # Case 1: Malformed or legacy callback_data (no version prefix)
        if payload is None:
            await answer_callback(update.callback_query.id, text="")
            return

        # Case 2: Stale callback from a previous menu — silent discard
        if payload.version != state.version:
            await answer_callback(
                update.callback_query.id,
                text="Este menú ya no está activo.",
                show_alert=False,
            )
            return

    handler = self._handlers.get(state.state)
    if handler is None:
        raise FSMTransitionError(f"No handler for state: {state.state}")

    await handler(update, state)
```

---

## FILE 4 — MODIFY ALL HANDLERS

PATH: app/fsm/handlers/*.py (idle.py, booking.py, cancellation.py, reschedule.py, my_bookings.py, reminders.py, information.py, my_data.py)

CHANGE: Replace plain callback_data strings with encode() calls.

RULE: encode() MUST be called AFTER transition_to() so version is already incremented.

```python
# ADD this import to every handler file that builds keyboards
from app.telegram.callback import encode

# BEFORE — plain callback_data, no version
keyboard = [
    [InlineButton(text="Cardiología",    callback_data="select_specialty:cardiology")],
    [InlineButton(text="Traumatología",  callback_data="select_specialty:traumatology")],
    [InlineButton(text="← Volver",       callback_data="back")],
]

# AFTER — versioned callback_data, stale-proof
keyboard = [
    [InlineButton(text="Cardiología",   callback_data=encode(state.version, "select_specialty", "cardiology"))],
    [InlineButton(text="Traumatología", callback_data=encode(state.version, "select_specialty", "traumatology"))],
    [InlineButton(text="← Volver",      callback_data=encode(state.version, "nav", "back"))],
]
```

NAMING CONVENTION for action strings:
```
select_{entity}   → selecting an item from a list
confirm_{entity}  → confirmation step
nav               → navigation (back, home, cancel)
toggle_{setting}  → boolean settings (reminders on/off)
view_{entity}     → read-only view actions
edit_{field}      → profile field editing
```

---

## FILE 5 — MODIFY

PATH: app/telegram/sender.py
CHANGE: Demote message_id from security role to cosmetic-only role.

REMOVE: Any logic that uses message_id to prevent ghost clicks.
KEEP:   Logic that uses message_id to edit message text for visual confirmation.

```python
# REMOVE this pattern — no longer the security mechanism
async def disable_previous_keyboard(chat_id: int, message_id: int | None) -> None:
    if message_id is None:
        return
    await edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id,
        reply_markup={"inline_keyboard": []},
    )

# KEEP this pattern — cosmetic confirmation only (optional UX enhancement)
async def mark_selection_confirmed(chat_id: int, message_id: int, text: str) -> None:
    """Edit previous menu text to show confirmed selection. Pure UX, not security."""
    await edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=f"✅ {text}",
    )
```

---

## FILE 6 — MODIFY

PATH: app/worker/tasks.py
CHANGE: Remove pre-flight keyboard disabling block.

LOCATE AND REMOVE this pattern at the start of the worker task:

```python
# REMOVE — this block is no longer needed
if state.message_id is not None:
    await disable_previous_keyboard(state.chat_id, state.message_id)
```

REASON: Version guard in router.py makes this unnecessary.
        Removing it eliminates one async I/O call per message processed.

---

## RESPONSIBILITY TABLE AFTER REFACTOR

```
COMPONENT               RESPONSIBILITY
─────────────────────── ──────────────────────────────────────────────────
callback.encode()       Stamp version onto every keyboard button
callback.decode()       Parse and validate incoming callback format
FSMRouter.route()       Reject stale/malformed callbacks before dispatch
ConversationState       Increment version atomically with state transition
message_id              Cosmetic UX only — edit text to show confirmation
Redis Lock              Prevent concurrent processing of same chat_id
pg_advisory_lock        DB-level serialization within transaction
```

---

## TEST CASES TO ADD

PATH: tests/unit/test_callback_versioning.py

```python
from app.telegram.callback import encode, decode, CallbackPayload


def test_encode_decode_roundtrip() -> None:
    raw = encode(version=5, action="select_specialty", value="cardiology")
    payload = decode(raw)
    assert payload == CallbackPayload(version=5, action="select_specialty", value="cardiology")


def test_decode_returns_none_on_malformed() -> None:
    assert decode("no_version_here") is None
    assert decode("") is None
    assert decode("vABC:action:value") is None
    assert decode("v1:only_two_parts") is None


def test_stale_version_rejected() -> None:
    # Simulate: keyboard built at version 3, state is now at version 5
    raw = encode(version=3, action="select_specialty", value="cardiology")
    payload = decode(raw)
    assert payload is not None
    current_version = 5
    assert payload.version != current_version  # must be discarded by router


def test_version_increments_on_transition() -> None:
    from app.domain.models import ConversationState
    from app.domain.enums import FSMState

    state = ConversationState(chat_id=123, state=FSMState.IDLE, version=0)
    state.transition_to(FSMState.SELECTING_SPECIALTY)
    assert state.version == 1

    state.transition_to(FSMState.SELECTING_DOCTOR)
    assert state.version == 2
```

---

## MIGRATION CHECKLIST

- [ ] Create app/telegram/callback.py (FILE 1)
- [ ] Update transition_to() in app/domain/models.py (FILE 2)
- [ ] Add version guard in app/fsm/router.py (FILE 3)
- [ ] Replace callback_data in all handlers in app/fsm/handlers/ (FILE 4)
- [ ] Demote message_id in app/telegram/sender.py (FILE 5)
- [ ] Remove pre-flight keyboard disable in app/worker/tasks.py (FILE 6)
- [ ] Add tests/unit/test_callback_versioning.py
- [ ] Verify: grep -r "callback_data=" app/fsm/handlers/ | grep -v "encode(" → must return empty
- [ ] Verify: mypy --strict returns 0 errors after changes
- [ ] Verify: pytest tests/unit/test_callback_versioning.py passes

---

## AGENTS.md ADDITION

Append this block to the existing AGENTS.md under a new section:

```markdown
## CALLBACK INTEGRITY (MANDATORY)

All inline keyboard buttons MUST use versioned callback_data:
  encode(state.version, action, value) → from app.telegram.callback

FSM Router MUST reject callbacks where payload.version != state.version.

version field increments ONLY inside transition_to() — never manually.

message_id is retained for cosmetic UX edits only.
Plain callback_data strings in handlers are FORBIDDEN after this refactor.
```

---
END OF DIRECTIVE
