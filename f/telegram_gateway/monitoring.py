from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Final, cast

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger: Final[logging.Logger] = logging.getLogger("telegram_gateway")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def log_structured(level: int, event: str, **kwargs: object) -> None:
    """Log in structured JSON format according to LAW-14 (no silent swallow/error dicts)."""
    payload = {
        "timestamp": time.time(),
        "level": logging.getLevelName(level),
        "event": event,
        **kwargs,
    }
    logger.log(level, json.dumps(payload))


class MetricsTracker:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self.prefix: Final[str] = "metrics:"

    async def increment_requests(self) -> None:
        try:
            await cast("Any", self.redis).incr(f"{self.prefix}requests_total")
        except Exception as e:
            log_structured(logging.ERROR, "metrics_increment_failed", error=str(e))

    async def increment_errors(self) -> None:
        try:
            await cast("Any", self.redis).incr(f"{self.prefix}errors_total")
        except Exception as e:
            log_structured(logging.ERROR, "metrics_increment_failed", error=str(e))

    async def record_processing_time(self, duration_ms: float) -> None:
        try:
            await cast("Any", self.redis).lpush(f"{self.prefix}processing_times_ms", str(duration_ms))
            await cast("Any", self.redis).ltrim(f"{self.prefix}processing_times_ms", 0, 999)
        except Exception as e:
            log_structured(logging.ERROR, "metrics_record_time_failed", error=str(e))

    async def record_telegram_send_time(self, duration_ms: float) -> None:
        try:
            await cast("Any", self.redis).lpush(f"{self.prefix}telegram_send_times_ms", str(duration_ms))
            await cast("Any", self.redis).ltrim(f"{self.prefix}telegram_send_times_ms", 0, 999)
        except Exception as e:
            log_structured(logging.ERROR, "metrics_record_tg_time_failed", error=str(e))

    async def record_internal_processing_time(self, duration_ms: float) -> None:
        try:
            await cast("Any", self.redis).lpush(f"{self.prefix}internal_processing_times_ms", str(duration_ms))
            await cast("Any", self.redis).ltrim(f"{self.prefix}internal_processing_times_ms", 0, 999)
        except Exception as e:
            log_structured(logging.ERROR, "metrics_record_internal_time_failed", error=str(e))

    async def record_queuing_delay(self, duration_ms: float) -> None:
        try:
            await cast("Any", self.redis).lpush(f"{self.prefix}queuing_delays_ms", str(duration_ms))
            await cast("Any", self.redis).ltrim(f"{self.prefix}queuing_delays_ms", 0, 999)
        except Exception as e:
            log_structured(logging.ERROR, "metrics_record_queue_failed", error=str(e))

    async def get_summary(self) -> dict[str, object]:
        """Retrieve metrics summary for basic monitoring dashboard."""
        try:
            reqs = await cast("Any", self.redis).get(f"{self.prefix}requests_total")
            errs = await cast("Any", self.redis).get(f"{self.prefix}errors_total")

            # Latency lists helper
            async def get_list_avg(key: str) -> tuple[float, int]:
                raw: Any = await cast("Any", self.redis).lrange(f"{self.prefix}{key}", 0, -1)
                items = [float(t) for t in cast("list[str]", raw) if t]
                avg = sum(items) / len(items) if items else 0.0
                return avg, len(items)

            avg_total, count_total = await get_list_avg("processing_times_ms")
            avg_tg, count_tg = await get_list_avg("telegram_send_times_ms")
            avg_internal, count_internal = await get_list_avg("internal_processing_times_ms")
            avg_queue, count_queue = await get_list_avg("queuing_delays_ms")

            return {
                "requests_total": int(reqs) if reqs else 0,
                "errors_total": int(errs) if errs else 0,
                "avg_total_time_ms": avg_total,
                "avg_telegram_send_time_ms": avg_tg,
                "avg_internal_processing_time_ms": avg_internal,
                "avg_queuing_delay_ms": avg_queue,
                "samples_count": count_total,
                "telegram_send_samples_count": count_tg,
                "internal_processing_samples_count": count_internal,
                "queuing_delay_samples_count": count_queue,
            }
        except Exception as e:
            log_structured(logging.ERROR, "metrics_summary_failed", error=str(e))
            raise RuntimeError(f"failed to fetch metrics: {e}") from e
