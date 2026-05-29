
import pytest
from httpx import AsyncClient, ASGITransport
from app.api.v1.webhook import create_webhook_router
from fastapi import FastAPI
from unittest.mock import AsyncMock

@pytest.fixture
def test_app(integration_container):
    app = FastAPI()
    router = create_webhook_router(integration_container)
    app.include_router(router, prefix="/api/v1")
    
    @app.get("/health")
    def health():
        return {"status": "healthy"}
        
    return app

@pytest.fixture
def client(test_app):
    return AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver")

@pytest.mark.asyncio
async def test_webhook_flow_integration(integration_container, clean_db_and_redis, test_app, client):
    payload = {
        "update_id": 123456789,
        "message": {
            "message_id": 1,
            "chat": {"id": 999111222},
            "text": "Hola"
        }
    }
    
    # Mock redis
    original_redis = integration_container.redis_client.client.set
    original_expire = integration_container.redis_client.client.expire
    integration_container.redis_client.client.set = AsyncMock(return_value=True)
    integration_container.redis_client.client.expire = AsyncMock()
    
    test_app.state.arq_pool = AsyncMock()
    
    try:
        response = await client.post("/api/v1/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        
        # Second POST (Duplicate)
        integration_container.redis_client.client.set.return_value = None
        response2 = await client.post("/api/v1/webhook", json=payload)
        assert response2.status_code == 200
        assert response2.json() == {"status": "duplicate"}
    finally:
        integration_container.redis_client.client.set = original_redis
        integration_container.redis_client.client.expire = original_expire

@pytest.mark.asyncio
async def test_webhook_rate_limiting(integration_container, clean_db_and_redis, test_app, client):
    test_app.state.arq_pool = AsyncMock()
    
    original_redis = integration_container.redis_client.client.pipeline
    mock_pipeline = AsyncMock()
    mock_pipeline_context = AsyncMock()
    from unittest.mock import MagicMock
    integration_container.redis_client.client.pipeline = MagicMock(return_value=mock_pipeline_context)
    mock_pipeline_context.__aenter__.return_value = mock_pipeline
    
    integration_container.redis_client.client.set = AsyncMock(return_value=True)
    
    try:
        for i in range(1, 35):
            payload = {
                "update_id": 1000 + i,
                "message": {"chat": {"id": 777}}
            }
            mock_pipeline.execute = AsyncMock(return_value=[i, -1 if i == 1 else 50])
            
            response = await client.post("/api/v1/webhook", json=payload)
            assert response.status_code == 200
            if i <= 30:
                assert response.json() == {"status": "ok"}
            else:
                assert response.json() == {"status": "rate_limited"}
    finally:
        integration_container.redis_client.client.pipeline = original_redis

@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
