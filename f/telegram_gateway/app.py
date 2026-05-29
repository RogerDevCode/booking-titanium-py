from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator  # noqa: TC003
from contextlib import asynccontextmanager
from typing import Any, Final

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..internal._redis_client import create_redis_client
from ._gateway_models import TelegramUpdate  # noqa: TC001
from .monitoring import MetricsTracker, log_structured

MODULE: Final[str] = "telegram_gateway_app"
REDIS_URL: Final[str] = os.getenv("REDIS_URL", "redis://redis:6379")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage app lifecycle and pool creations."""
    log_structured(logging.INFO, "api_startup_initiated")
    # Initialize arq redis pool
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    # Initialize direct redis client for idempotency check
    app.state.redis = await create_redis_client(REDIS_URL)
    yield
    # Cleanup pools
    await app.state.arq_pool.close()
    await app.state.redis.aclose()
    log_structured(logging.INFO, "api_shutdown_completed")


app = FastAPI(title="Telegram Gateway API", lifespan=lifespan)


async def get_redis(request: Request) -> Any:  # noqa: ANN401
    return request.app.state.redis


async def get_arq(request: Request) -> Any:  # noqa: ANN401
    return request.app.state.arq_pool


@app.get("/monitoring/metrics", response_class=JSONResponse)
async def get_metrics(redis: Any = Depends(get_redis)) -> JSONResponse:  # noqa: ANN401, B008
    """Endpoint for retrieving APM latency and throughput metrics."""
    try:
        tracker = MetricsTracker(redis)
        summary = await tracker.get_summary()
        return JSONResponse(status_code=status.HTTP_200_OK, content=summary)
    except Exception as e:
        log_structured(logging.ERROR, "metrics_endpoint_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve metrics: {e}",
        ) from e


@app.post("/webhook/telegram", response_class=JSONResponse)
async def telegram_webhook(
    update: TelegramUpdate,
    redis: Any = Depends(get_redis),  # noqa: ANN401, B008
    arq_pool: Any = Depends(get_arq),  # noqa: ANN401, B008
) -> JSONResponse:
    """Intake endpoint for Telegram updates.
    Ensures idempotency using Redis, queues to arq worker, and returns 200 OK immediately.
    """
    try:
        # Check idempotency
        idemp_key = f"idemp:{update.update_id}"
        # Set with NX and EX = 1 hour (3600 seconds)
        is_new = await redis.set(idemp_key, "1", nx=True, ex=3600)
        if not is_new:
            log_structured(
                logging.INFO,
                "update_idempotency_duplicate_ignored",
                update_id=update.update_id,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"status": "duplicate_ignored", "update_id": update.update_id},
            )

        # Enqueue job into arq worker with current ingest timestamp
        update_json = update.model_dump_json()
        await arq_pool.enqueue_job("process_telegram_update", update_json, time.time())

        log_structured(
            logging.INFO,
            "update_enqueued_successfully",
            update_id=update.update_id,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "enqueued", "update_id": update.update_id},
        )

    except Exception as e:
        log_structured(
            logging.ERROR,
            "webhook_ingestion_failed",
            error=str(e),
            update_id=update.update_id,
        )
        # Never swallow silently, raise to trigger logs and bubble up according to LAW-14
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook ingestion error: {e}",
        ) from e
