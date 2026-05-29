from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from app.core.config import settings  # noqa: E402
settings.REDIS_URL = "redis://localhost:6379"

from app.main import app  # noqa: E402

client = TestClient(app)

def test_webhook_flow_integration():
    """
    Test for the full entry-point flow:
    Webhook -> Idempotency Check -> Task Enqueue
    """
    
    payload = {
        "update_id": 99999123,
        "message": {
            "message_id": 1,
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 999, "first_name": "Test", "last_name": "User"},
            "text": "1"
        }
    }
    
    # We mock redis_client to avoid connection check error
    with patch("app.api.v1.webhook.redis_client") as mock_redis:
        mock_set = AsyncMock()
        mock_redis.client.expire = AsyncMock()
        
        mock_redis.client.set = mock_set
        mock_pipeline = AsyncMock()
        mock_pipeline_context = AsyncMock()
        mock_redis.client.pipeline.return_value = mock_pipeline_context
        mock_pipeline_context.__aenter__.return_value = mock_pipeline
        mock_pipeline.incr = AsyncMock()
        mock_pipeline.ttl = AsyncMock()
        mock_pipeline.execute = AsyncMock(return_value=[1, -1])
        
        # We need to mock request.app.state.arq_pool since lifespan didn't run
        app.state.arq_pool = AsyncMock()
        
        response = client.post("/api/v1/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_redis.client.expire.assert_called_once_with("rate_limit:999", 60)
        app.state.arq_pool.enqueue_job.assert_called_once_with("process_message", payload)
        
        # 2. Second POST (Duplicate): Simulate duplicate
        mock_set.return_value = None
        
        response2 = client.post("/api/v1/webhook", json=payload)
        assert response2.status_code == 200
        assert response2.json() == {"status": "duplicate"}

def test_webhook_rate_limiting():
    """
    Test that the webhook blocks messages after 30 requests from the same chat_id.
    """
    with patch("app.api.v1.webhook.redis_client") as mock_redis:
        mock_set = AsyncMock(return_value=True) # Always new update_id
        mock_redis.client.expire = AsyncMock()
        
        mock_redis.client.set = mock_set
        mock_pipeline = AsyncMock()
        mock_pipeline_context = AsyncMock()
        mock_redis.client.pipeline.return_value = mock_pipeline_context
        mock_pipeline_context.__aenter__.return_value = mock_pipeline
        mock_pipeline.incr = AsyncMock()
        mock_pipeline.ttl = AsyncMock()
        
        app.state.arq_pool = AsyncMock()
        
        for i in range(1, 35):
            payload = {
                "update_id": 1000 + i,
                "message": {"chat": {"id": 777}}
            }
            
            mock_pipeline.execute = AsyncMock(return_value=[i, -1 if i == 1 else 50])
            
            response = client.post("/api/v1/webhook", json=payload)
            assert response.status_code == 200
            
            if i <= 30:
                assert response.json() == {"status": "ok"}
            else:
                assert response.json() == {"status": "rate_limited"}
                
        # ARQ should only be called 30 times
        assert app.state.arq_pool.enqueue_job.call_count == 30

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

