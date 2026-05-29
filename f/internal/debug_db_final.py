import asyncio

from f.internal._db_client import create_db_client


async def _main() -> None:
    conn = await create_db_client()
    try:
        print("--- DATABASES LIST ---")
        rows = await conn.fetch("SELECT datname FROM pg_database WHERE datistemplate = false")
        for r in rows:
            print(f"DB: {r['datname']}")
    finally:
        await conn.close()


def main() -> None:
    asyncio.run(_main())
