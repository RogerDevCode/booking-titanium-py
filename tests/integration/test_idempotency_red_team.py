import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.db.redis_client import redis_client
from app.core.config import settings
from unittest.mock import AsyncMock

@pytest.fixture
async def setup_env():
    settings.REDIS_URL = "redis://localhost:6379"
    await redis_client.connect()
    yield
    await redis_client.disconnect()

@pytest.mark.asyncio
async def test_idempotency_concurrency_and_ttl(setup_env):
    """
    Test that the webhook idempotency mechanism works correctly under high concurrency
    and that the TTL is correctly set to prevent memory leaks.
    """
    app = create_app()
    # Mock ARQ pool to avoid enqueuing real jobs during the test
    mock_arq_pool = AsyncMock()
    app.state.arq_pool = mock_arq_pool

    chat_id = 44444
    update_id = 99999123

    # 1. Reset rate limit key and idempotency key
    await redis_client.client.delete(f"rate_limit:{chat_id}")
    key_idemp = f"webhook_seen:{update_id}"
    await redis_client.client.delete(key_idemp)

    # 2. Prepare payload
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Test", "last_name": "User"},
            "text": "1"
        }
    }

    # 3. Fire 50 concurrent requests with the EXACT SAME update_id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        tasks = []
        for _ in range(50):
            # Same payload, simulating Telegram retry storm or a DDoS attack
            tasks.append(ac.post("/api/v1/webhook", json=payload))
        
        responses = await asyncio.gather(*tasks)

    # 4. Check results
    status_counts = {"ok": 0, "duplicate": 0, "rate_limited": 0}
    for resp in responses:
        assert resp.status_code == 200
        status = resp.json().get("status")
        status_counts[status] = status_counts.get(status, 0) + 1

    # Exactly 1 should pass (the one that won the race condition in Redis SET NX)
    assert status_counts["ok"] == 1
    # The other 49 must be rejected immediately without hitting the rate limiter or ARQ
    assert status_counts["duplicate"] == 49
    assert status_counts["rate_limited"] == 0

    # ARQ should have been called exactly once
    assert mock_arq_pool.enqueue_job.call_count == 1

    # 5. Verify the key TTL (prevent memory leak)
    # The TTL should be 3600 seconds (or slightly less because some time passed).
    ttl = await redis_client.client.ttl(key_idemp)
    
    # -1 means no expiry (memory leak!).
    # -2 means doesn't exist.
    assert ttl > 0
    assert ttl <= 3600
    
    # We also assert that it's clearly less than or equal to 3600, 
    # to guarantee we successfully reduced it from 86400
    assert ttl <= 3600

    # Clean up
    await redis_client.client.delete(f"rate_limit:{chat_id}")
    await redis_client.client.delete(key_idemp)
