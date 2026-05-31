import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.worker.tasks import make_process_message

@pytest.mark.asyncio
async def test_conversation_logger_inbound_and_outbound(integration_container, clean_db_and_redis):
    """
    Test verifying that the conversational logger successfully captures
    inbound messages (user inputs) and outbound messages (bot replies enqueued and flushed).
    """
    mock_resp = AsyncMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 987654}}
    mock_resp.raise_for_status = MagicMock()
    
    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        process_message = make_process_message(integration_container)
        chat_id = 987654321
        
        # 1. Send /start as an inbound user message
        payload = {
            "update_id": 888888,
            "message": {
                "message_id": 1,
                "chat": {"id": chat_id, "first_name": "Audit", "last_name": "User"},
                "text": "/start"
            }
        }
        
        await process_message({}, payload)
        
        # 2. Check inbound logs
        inbound_logs = await integration_container.db_client.fetch(
            "SELECT * FROM conversations WHERE client_id = $1 AND direction = 'inbound' ORDER BY created_at ASC",
            chat_id
        )
        assert len(inbound_logs) == 1
        assert inbound_logs[0]["content"] == "/start"
        assert inbound_logs[0]["direction"] == "inbound"
        assert inbound_logs[0]["channel"] == "telegram"
        
        # 3. Check outbound logs
        outbound_logs = await integration_container.db_client.fetch(
            "SELECT * FROM conversations WHERE client_id = $1 AND direction = 'outbound' ORDER BY created_at ASC",
            chat_id
        )
        # Should have enqueued and flushed the welcome message
        assert len(outbound_logs) >= 1
        assert "Bienvenido" in outbound_logs[0]["content"]
        assert outbound_logs[0]["direction"] == "outbound"
        
        # Ensure metadata contains reply_markup
        metadata = inbound_logs[0]["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        assert metadata.get("update_id") == 888888
        
        out_metadata = outbound_logs[0]["metadata"]
        if isinstance(out_metadata, str):
            out_metadata = json.loads(out_metadata)
        assert "reply_markup" in out_metadata
