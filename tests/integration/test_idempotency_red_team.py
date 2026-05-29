import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.api.v1.webhook import create_webhook_router
from fastapi import FastAPI
from unittest.mock import AsyncMock

@pytest.fixture
def test_app(integration_container):
    app = FastAPI()
    router = create_webhook_router(integration_container)
    app.include_router(router, prefix="/api/v1")
    return app

@pytest.mark.asyncio
async def test_idempotency_concurrency_and_ttl(integration_container, clean_db_and_redis, test_app):
    mock_arq_pool = AsyncMock()
    test_app.state.arq_pool = mock_arq_pool

    chat_id = 44444
    update_id = 99999123

    # 1. Reset rate limit key and idempotency key
    await integration_container.redis_client.client.delete(f"rate_limit:{chat_id}")
    key_idemp = f"webhook_seen:{update_id}"
    await integration_container.redis_client.client.delete(key_idemp)

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
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        tasks = []
        for _ in range(50):
            tasks.append(ac.post("/api/v1/webhook", json=payload))
        
        responses = await asyncio.gather(*tasks)

    # 4. Check results
    status_counts = {"ok": 0, "duplicate": 0, "rate_limited": 0}
    for resp in responses:
        assert resp.status_code == 200
        status = resp.json().get("status")
        status_counts[status] = status_counts.get(status, 0) + 1

    assert status_counts["ok"] == 1
    assert status_counts["duplicate"] == 49
    assert status_counts["rate_limited"] == 0

    assert mock_arq_pool.enqueue_job.call_count == 1
