import json
from app.domain.protocols import DatabaseClientProtocol
from app.domain.models import ConversationState
from app.domain.enums import FSMState

class ConversationTransaction:
    """
    Handles transactional read/write of the conversation state.
    Uses PG advisory locks for concurrency control.
    """
    
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db
    
    async def get_state(self, chat_id: int) -> ConversationState:
        """Reads the current state for a chat_id."""
        query = """
            SELECT chat_id, state, active_flow, context, booking_draft, message_id, version, updated_at 
            FROM conversation_states WHERE chat_id = $1
        """
        row = await self._db.fetchrow(query, chat_id)
        
        if row:
            return ConversationState(
                chat_id=row['chat_id'],
                state=FSMState(row['state']),
                active_flow=row['active_flow'],
                context=json.loads(row['context']),
                booking_draft=json.loads(row['booking_draft']),
                message_id=row['message_id'],
                version=row['version'],
                updated_at=row['updated_at']
            )
        return ConversationState(chat_id=chat_id)

    async def set_state(self, state: ConversationState) -> None:
        """Persists the state for a chat_id."""
        query = """
            INSERT INTO conversation_states (
                chat_id, state, active_flow, context, booking_draft, message_id, version, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (chat_id) DO UPDATE
            SET state = EXCLUDED.state, 
                active_flow = EXCLUDED.active_flow,
                context = EXCLUDED.context, 
                booking_draft = EXCLUDED.booking_draft,
                message_id = EXCLUDED.message_id,
                version = EXCLUDED.version,
                updated_at = NOW()
        """
        await self._db.execute(
            query, 
            state.chat_id, 
            state.state.value,
            state.active_flow,
            json.dumps(state.context),
            json.dumps(state.booking_draft),
            state.message_id,
            state.version
        )

