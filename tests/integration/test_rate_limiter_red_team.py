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
async def test_rate_limiter_pipeline_concurrency(integration_container, clean_db_and_redis, test_app):
    chat_id = 88888
    
    mock_arq_pool = AsyncMock()
    test_app.state.arq_pool = mock_arq_pool

    payload = {
        "update_id": 0,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "text": "1"
        }
    }

    # Reset Rate Limit
    await integration_container.redis_client.client.delete(f"rate_limit:{chat_id}")
    
    # Send 40 requests simultaneously
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        tasks = []
        for i in range(40):
            p = dict(payload)
            p['update_id'] = 1000 + i  # Different update_id
            tasks.append(ac.post("/api/v1/webhook", json=p))
            
        responses = await asyncio.gather(*tasks)

    status_counts = {"ok": 0, "duplicate": 0, "rate_limited": 0, "ignored": 0}
    for resp in responses:
        assert resp.status_code == 200
        status = resp.json().get("status")
        status_counts[status] = status_counts.get(status, 0) + 1

    # In a perfect concurrency world, exactly 30 should pass and 10 should be rate limited
    assert status_counts["ok"] == 30
    assert status_counts["rate_limited"] == 10
    
    # Double check Redis TTL to avoid leaks
    ttl = await integration_container.redis_client.client.ttl(f"rate_limit:{chat_id}")
    assert 0 < ttl <= 60
