# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "asyncpg>=0.30.0",
#   "pydantic>=2.10.0"
# ]
# ///
from __future__ import annotations


async def _main_async(pg_url: str) -> dict[str, object]:
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    import asyncpg

    parsed = urlparse(pg_url)
    connect_kwargs: dict[str, object] = {}
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        asyncpg_params = {"statement_cache_size", "max_cached_statement_lifetime"}
        extracted = {k: v for k, v in params.items() if k in asyncpg_params}
        remaining = {k: v for k, v in params.items() if k not in asyncpg_params}
        for k, v in extracted.items():
            connect_kwargs[k] = int(v[0]) if v[0].isdigit() else v[0]
        pg_url = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in remaining.items()})))

    conn = await asyncpg.connect(pg_url, **connect_kwargs)
    try:
        # 1. Specialty — reuse if exists
        spec = await conn.fetchrow("SELECT specialty_id, name FROM specialties WHERE name = 'Medicina General' LIMIT 1")
        if not spec:
            spec = await conn.fetchrow(
                """
                INSERT INTO specialties (name, description, category, sort_order, is_active)
                VALUES ('Medicina General', 'Consulta médica general', 'Medicina', 1, true)
                RETURNING specialty_id, name
                """
            )
        if not spec:
            return {"error": "specialty insert failed"}
        specialty_id = str(spec["specialty_id"])
        specialty_name = str(spec["name"])

        # 2. Provider — reuse if exists
        prov = await conn.fetchrow(
            "SELECT provider_id, name FROM providers WHERE email = 'test@autoagenda.test' LIMIT 1"
        )
        if not prov:
            prov = await conn.fetchrow(
                """
                INSERT INTO providers (name, email, phone, is_active, specialty_id)
                VALUES ('Dr. Test', 'test@autoagenda.test', '+1-000-000-0000',
                        true, $1::uuid)
                RETURNING provider_id, name
                """,
                specialty_id,
            )
        else:
            # Ensure specialty_id is set on existing provider
            await conn.execute(
                "UPDATE providers SET specialty_id = $1::uuid, is_active = true WHERE email = 'test@autoagenda.test'",
                specialty_id,
            )
        if not prov:
            return {"error": "provider insert failed"}
        provider_id = str(prov["provider_id"])
        provider_name = str(prov["name"])

        # 3. Service — reuse if exists
        svc = await conn.fetchrow(
            "SELECT service_id, name FROM services WHERE provider_id = $1::uuid LIMIT 1",
            provider_id,
        )
        if not svc:
            svc = await conn.fetchrow(
                """
                INSERT INTO services (provider_id, name, description, duration_minutes,
                                      buffer_minutes, price_cents, currency)
                VALUES ($1::uuid, 'Consulta General', 'Consulta médica general', 30, 10, 0, 'CLP')
                RETURNING service_id, name
                """,
                provider_id,
            )
        if not svc:
            return {"error": "service insert failed"}

        return {
            "ok": True,
            "specialty": {"id": specialty_id, "name": specialty_name},
            "provider": {"id": provider_id, "name": provider_name},
            "service_id": str(svc["service_id"]),
        }
    finally:
        await conn.close()


def main(pg_url: str) -> dict[str, object]:
    import asyncio

    return asyncio.run(_main_async(pg_url))
