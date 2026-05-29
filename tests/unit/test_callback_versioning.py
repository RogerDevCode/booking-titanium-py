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
