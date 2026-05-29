from fastapi import APIRouter, Request
from typing import Optional
from app.core.logging import logger
from app.container import Container

def create_webhook_router(container: Container) -> APIRouter:
    router = APIRouter()

    def _extract_chat_id(payload: dict) -> Optional[int]:
        """Extacts the chat_id from various Telegram payload structures."""
        if "message" in payload:
            return payload["message"].get("chat", {}).get("id")
        if "callback_query" in payload:
            return payload["callback_query"].get("message", {}).get("chat", {}).get("id")
        if "edited_message" in payload:
            return payload["edited_message"].get("chat", {}).get("id")
        return None

    @router.post("/webhook")
    async def telegram_webhook(request: Request):
        """
        Ingress point for Telegram updates.
        Parses the update, checks idempotency and rate limits, and enqueues a processing job in ARQ.
        """
        payload = await request.json()
        update_id = payload.get("update_id")
        
        if not update_id:
            # Invalid payload from Telegram
            return {"status": "ignored", "reason": "missing_update_id"}

        chat_id = _extract_chat_id(payload)
        if not chat_id:
            # If there's no chat_id (e.g. inline query, channel post), we ignore it safely
            return {"status": "ignored", "reason": "unsupported_update_type"}

        # 1. Idempotency Check (O(1) in Redis)
        key_idemp = f"webhook_seen:{update_id}"
        is_new = await container.redis_client.client.set(key_idemp, "1", nx=True, ex=3600)
        
        if not is_new:
            logger.warning("Duplicate webhook received, ignoring", update_id=update_id)
            return {"status": "duplicate"}

        # 2. Rate Limiting Aggressive In-Memory (30 messages per minute)
        key_rate = f"rate_limit:{chat_id}"
        async with container.redis_client.client.pipeline(transaction=True) as pipe:
            pipe.incr(key_rate)
            pipe.ttl(key_rate)
            results = await pipe.execute()
            count = results[0]
            ttl = results[1]
            
        if ttl < 0:
            await container.redis_client.client.expire(key_rate, 60)
            
        if count > 30:
            logger.warning("Rate limit exceeded for chat_id", chat_id=chat_id, count=count)
            # Return 200 OK so Telegram stops retrying, but don't process it.
            return {"status": "rate_limited"}

        logger.info("Received new Telegram update", update_id=update_id, chat_id=chat_id)
        
        # 3. Enqueue Job using global pool
        arq_pool = request.app.state.arq_pool
        await arq_pool.enqueue_job("process_message", payload)
        
        return {"status": "ok"}

    return router

# Fallback for old tests that import router directly
router = APIRouter()
