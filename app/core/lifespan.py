from contextlib import asynccontextmanager
from fastapi import FastAPI
from arq import create_pool
from arq.connections import RedisSettings
from app.core.logging import setup_logging, logger
from app.container import Container

def create_lifespan(container: Container):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        setup_logging()
        logger.info("Starting Titanium Booking Engine...")
        
        await container.db_client.connect()
        logger.info("Database connection established.")
        
        await container.redis_client.connect()
        logger.info("Redis connection established.")
        
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(container.settings.REDIS_URL))
        logger.info("ARQ Pool established.")
        
        yield
        
        # Shutdown
        logger.info("Shutting down Titanium Booking Engine...")
        if hasattr(app.state, 'arq_pool'):
            await app.state.arq_pool.close()
        
        await container.redis_client.disconnect()
        logger.info("Redis connection closed.")
        
        await container.db_client.disconnect()
        logger.info("Database connection closed.")
        
    return lifespan

# Temporary fallback
from app.core.config import settings  # noqa: E402
try:
    from app.container import build_container
    _temp_container = build_container(settings)
    lifespan = create_lifespan(_temp_container)
except Exception:
    pass
