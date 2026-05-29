import pytest
import redis.asyncio as redis_async
from app.db.redis_client import redis_client
from app.core.config import settings

@pytest.mark.asyncio
async def test_redis_client_is_async_type():
    """
    Red Team / Unit test to verify that the redis client is strictly
    an async client instance at runtime, complying with Suggestion S-5.
    """
    # Ensure it's disconnected first
    await redis_client.disconnect()
    
    settings.REDIS_URL = "redis://localhost:6379"
    await redis_client.connect()
    
    # Check the runtime type
    client_instance = redis_client.client
    
    assert isinstance(client_instance, redis_async.Redis), "Client must be an instance of redis.asyncio.Redis"
    
    # Test that we can indeed await its methods
    pong = await client_instance.ping()
    assert pong is True
    
    await redis_client.disconnect()
