import time

import httpx

from ..internal._db_client import create_db_client
from ._health_models import ComponentStatus


async def check_database() -> ComponentStatus:
    start = time.time()
    try:
        conn = await create_db_client()
        await conn.fetch("SELECT 1")
        latency = int((time.time() - start) * 1000)
        await conn.close()
        return {"component": "database", "status": "healthy", "latency_ms": latency, "message": "OK"}
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return {"component": "database", "status": "unhealthy", "latency_ms": latency, "message": str(e)}


async def check_gcal(token: str | None) -> ComponentStatus:
    if not token:
        return {
            "component": "gcal",
            "status": "not_configured",
            "latency_ms": 0,
            "message": "GCAL_ACCESS_TOKEN not set",
        }

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1",
                headers={"Authorization": f"Bearer {token}"},
            )
            latency = int((time.time() - start) * 1000)
            if res.status_code == 200:
                return {"component": "gcal", "status": "healthy", "latency_ms": latency, "message": "OK"}
            return {
                "component": "gcal",
                "status": "degraded",
                "latency_ms": latency,
                "message": f"HTTP {res.status_code}",
            }
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return {"component": "gcal", "status": "unhealthy", "latency_ms": latency, "message": str(e)}


async def check_telegram(token: str | None) -> ComponentStatus:
    if not token:
        return {
            "component": "telegram",
            "status": "not_configured",
            "latency_ms": 0,
            "message": "TELEGRAM_BOT_TOKEN not set",
        }

    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            latency = int((time.time() - start) * 1000)
            if res.status_code == 200:
                return {"component": "telegram", "status": "healthy", "latency_ms": latency, "message": "OK"}
            return {
                "component": "telegram",
                "status": "degraded",
                "latency_ms": latency,
                "message": f"HTTP {res.status_code}",
            }
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return {"component": "telegram", "status": "unhealthy", "latency_ms": latency, "message": str(e)}


def check_gmail(pwd: str | None) -> ComponentStatus:
    if not pwd:
        return {"component": "gmail", "status": "not_configured", "latency_ms": 0, "message": "GMAIL_PASSWORD not set"}
    return {"component": "gmail", "status": "healthy", "latency_ms": 0, "message": "OK"}
