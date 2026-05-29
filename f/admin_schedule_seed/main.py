# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "asyncpg>=0.30.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0"
# ]
# ///
from __future__ import annotations

import asyncio
from typing import Final

from f.internal._config import DEFAULT_TIMEZONE

from ..internal._db_client import create_db_client
from ..internal._wmill_adapter import log

"""
PRE-FLIGHT CHECKLIST
Mission         : Seed correct provider schedules (Mon-Fri 09:00-18:00, America/Santiago)
DB Tables Used  : providers, timezones, provider_schedules
Concurrency Risk: NO — idempotent UPSERT
GCal Calls      : NO
Idempotency Key : ON CONFLICT clause
RLS Tenant ID   : NO — admin operation
"""

MODULE: Final[str] = "admin_schedule_seed"

# day_of_week: 0=Sun,1=Mon,2=Tue,3=Wed,4=Thu,5=Fri,6=Sat (matches Postgres EXTRACT DOW)
WORKDAYS: Final[list[int]] = [1, 2, 3, 4, 5]  # Lunes a Viernes
SCHEDULE_START: Final[str] = "09:00"
SCHEDULE_END: Final[str] = "18:00"
TARGET_TZ: Final[str] = DEFAULT_TIMEZONE


async def _main_async(dry_run: bool = False) -> dict[str, object]:
    db = await create_db_client()
    try:
        # 1. Resolve America/Santiago timezone_id
        tz_row = await db.fetchrow(
            "SELECT id FROM timezones WHERE name = $1 LIMIT 1",
            TARGET_TZ,
        )
        if not tz_row:
            # Try to find any Chile/Santiago variant
            tz_row = await db.fetchrow(
                "SELECT id, name FROM timezones WHERE name ILIKE $1 LIMIT 1",
                "%Santiago%",
            )
            if not tz_row:
                return {
                    "success": False,
                    "error": f"Timezone '{TARGET_TZ}' not found in timezones table. "
                    "Available timezones: run SELECT name FROM timezones ORDER BY name.",
                }
            log("TZ_FALLBACK", found=str(tz_row["name"]), module=MODULE)

        tz_id = int(str(tz_row["id"]))
        log("TZ_RESOLVED", tz_id=tz_id, tz_name=TARGET_TZ, module=MODULE)

        # 2. Fetch all active providers
        providers = await db.fetch(
            "SELECT provider_id, name, timezone_id FROM providers WHERE is_active = true ORDER BY name"
        )
        if not providers:
            return {"success": True, "message": "No active providers found.", "providers_updated": 0}

        providers_updated = 0
        schedules_upserted = 0

        for p in providers:
            pid = str(p["provider_id"])
            pname = str(p["name"])
            current_tz = p["timezone_id"]

            if dry_run:
                log(
                    "DRY_RUN_PROVIDER",
                    provider=pname,
                    current_tz_id=current_tz,
                    target_tz_id=tz_id,
                    module=MODULE,
                )
                providers_updated += 1
                schedules_upserted += len(WORKDAYS)
                continue

            # 3. Update provider timezone if not already set correctly
            if current_tz != tz_id:
                await db.execute(
                    "UPDATE providers SET timezone_id = $1, updated_at = NOW() WHERE provider_id = $2::uuid",
                    tz_id,
                    pid,
                )
                log("PROVIDER_TZ_UPDATED", provider=pname, from_tz=current_tz, to_tz=tz_id, module=MODULE)
            providers_updated += 1

            # 4. Upsert schedule for each workday
            for day in WORKDAYS:
                await db.execute(
                    """
                    INSERT INTO provider_schedules (provider_id, day_of_week, start_time, end_time)
                    VALUES ($1::uuid, $2, $3::time, $4::time)
                    ON CONFLICT (provider_id, day_of_week, start_time)
                    DO UPDATE SET
                        end_time = EXCLUDED.end_time
                    """,
                    pid,
                    day,
                    SCHEDULE_START,
                    SCHEDULE_END,
                )
                schedules_upserted += 1

            log(
                "SCHEDULES_SEEDED",
                provider=pname,
                days=WORKDAYS,
                start=SCHEDULE_START,
                end=SCHEDULE_END,
                module=MODULE,
            )

        result: dict[str, object] = {
            "success": True,
            "dry_run": dry_run,
            "timezone": TARGET_TZ,
            "timezone_id": tz_id,
            "providers_updated": providers_updated,
            "schedules_upserted": schedules_upserted,
            "schedule": f"{SCHEDULE_START}-{SCHEDULE_END} Mon-Fri",
        }
        log("SEED_COMPLETE", **{k: str(v) for k, v in result.items()}, module=MODULE)
        return result

    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        log("SEED_ERROR", error=str(e), traceback=tb, module=MODULE)
        raise RuntimeError(f"Schedule seed failed: {e}") from e
    finally:
        await db.close()


def main(dry_run: bool = False) -> dict[str, object]:
    return asyncio.run(_main_async(dry_run=dry_run))
