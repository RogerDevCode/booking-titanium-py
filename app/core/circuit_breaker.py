import time
from app.core.logging import logger
from app.domain.protocols import RedisClientProtocol

class CircuitBreakerOpenException(Exception):
    """Raised when the circuit breaker is open."""
    pass

class RedisCircuitBreaker:
    """
    A distributed Circuit Breaker pattern using Redis.
    Shared across all workers.
    """
    
    def __init__(self, redis_client: RedisClientProtocol, name: str, failure_threshold: int = 3, recovery_timeout: int = 60):
        self._redis = redis_client
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.key_failures = f"cb:{name}:failures"
        self.key_last_failure = f"cb:{name}:last_failure"
        self.key_state = f"cb:{name}:state" # values: CLOSED, OPEN, HALF-OPEN

    async def get_state(self) -> str:
        state = await self._redis.client.get(self.key_state)
        if not state:
            return "CLOSED"
        
        if state == "OPEN":
            last_failure = await self._redis.client.get(self.key_last_failure)
            if last_failure:
                elapsed = time.time() - float(last_failure)
                if elapsed > self.recovery_timeout:
                    # Transition to HALF-OPEN
                    await self._redis.client.set(self.key_state, "HALF-OPEN")
                    return "HALF-OPEN"
        return state

    async def record_failure(self):
        failures = await self._redis.client.incr(self.key_failures)
        await self._redis.client.set(self.key_last_failure, str(time.time()))
        
        if failures >= self.failure_threshold:
            await self._redis.client.set(self.key_state, "OPEN")
            logger.error("Circuit Breaker TRIPPED to OPEN", name=self.name, failures=failures)
        else:
            logger.warning("Circuit Breaker recorded failure", name=self.name, failures=failures)

    async def record_success(self):
        state = await self._redis.client.get(self.key_state)
        if state in ["OPEN", "HALF-OPEN"] or await self._redis.client.get(self.key_failures):
            await self._redis.client.set(self.key_state, "CLOSED")
            await self._redis.client.delete(self.key_failures)
            await self._redis.client.delete(self.key_last_failure)
            logger.info("Circuit Breaker RESET to CLOSED", name=self.name)
