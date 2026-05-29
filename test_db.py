import asyncio
from app.db.connection import db_client
from app.core.config import settings

settings.DATABASE_URL = "postgresql://booking:booking@localhost:5432/booking"

async def check():
    await db_client.connect()
    rows = await db_client.fetch("SELECT category, provider_id, content FROM knowledge_base WHERE provider_id IS NOT NULL LIMIT 5")
    for r in rows:
        print(dict(r))
    await db_client.disconnect()

if __name__ == '__main__':
    asyncio.run(check())
