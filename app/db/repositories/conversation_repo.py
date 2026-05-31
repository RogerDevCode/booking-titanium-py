from typing import Optional, Dict, Any
import json
from app.domain.protocols import DatabaseClientProtocol
from app.core.logging import logger

class ConversationRepository:
    def __init__(self, db: DatabaseClientProtocol) -> None:
        self._db = db

    async def log_message(
        self,
        client_id: int,
        direction: str,
        content: str,
        intent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        provider_id: Optional[str] = None,
    ) -> str:
        """
        Logs a conversation message (inbound or outbound) to the database.
        Returns the message UUID as a string.
        """
        query = """
            INSERT INTO conversations (
                client_id, direction, content, intent, metadata, provider_id
            ) VALUES (
                $1, $2, $3, $4, $5::jsonb, $6::uuid
            ) RETURNING message_id
        """
        meta_json = json.dumps(metadata) if metadata else "{}"
        
        # Validate UUID if provider_id is provided
        p_id = None
        if provider_id:
            try:
                from uuid import UUID
                UUID(str(provider_id))
                p_id = str(provider_id)
            except ValueError:
                logger.warning("Invalid UUID for provider_id, skipping logging with provider_id", provider_id=provider_id)
                p_id = None
                
        row = await self._db.fetchrow(query, client_id, direction, content, intent, meta_json, p_id)
        if not row:
            raise RuntimeError("Failed to log conversation message: no message_id returned")
            
        return str(row["message_id"])
