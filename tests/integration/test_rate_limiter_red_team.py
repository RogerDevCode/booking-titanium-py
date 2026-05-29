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
async def test_rate_limiter_pipeline_concurrency(setup_env):
    """
    Test that the rate limiter handles concurrent requests correctly
    using the pipeline and that the expiration is set properly without memory leaks.
    """
    app = create_app()
    # Mock ARQ pool to avoid enqueuing real jobs during the test
    mock_arq_pool = AsyncMock()
    app.state.arq_pool = mock_arq_pool

    chat_id = 88888
    
    # 1. Reset rate limit key and idempotency keys
    key_rate = f"rate_limit:{chat_id}"
    await redis_client.client.delete(key_rate)
    for i in range(50):
        await redis_client.client.delete(f"webhook_seen:{i+1}")

    # 2. Prepare payload
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Test", "last_name": "User"},
            "text": "1"
        }
    }

    # 3. Fire 50 concurrent requests
    # Limit is 10. So exactly 10 should be "ok", and 40 should be "rate_limited" (or duplicate, but wait!)
    # Ah, the webhook also has an idempotency check (webhook_seen:{update_id}).
    # If we use the exact same update_id, the first one gets it, the rest return "duplicate".
    # We must use different update_ids to bypass the idempotency check and actually hit the rate limiter!
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        tasks = []
        for i in range(50):
            new_payload = dict(payload)
            new_payload["update_id"] = i + 1
            tasks.append(ac.post("/api/v1/webhook", json=new_payload))
        
        responses = await asyncio.gather(*tasks)

    # 4. Check results
    status_counts = {"ok": 0, "rate_limited": 0, "duplicate": 0}
    for resp in responses:
        assert resp.status_code == 200
        status = resp.json().get("status")
        status_counts[status] = status_counts.get(status, 0) + 1

    assert status_counts["ok"] == 10
    assert status_counts["rate_limited"] == 40
    assert status_counts["duplicate"] == 0

    # 5. Verify the key TTL (prevent memory leak)
    # The TTL should be 60 seconds (or slightly less because some time passed).
    ttl = await redis_client.client.ttl(key_rate)
    
    # -1 means no expiry (memory leak!).
    # -2 means doesn't exist.
    assert ttl > 0
    assert ttl <= 60

    # Clean up
    await redis_client.client.delete(key_rate)
    for i in range(50):
        await redis_client.client.delete(f"webhook_seen:{i+1}")
