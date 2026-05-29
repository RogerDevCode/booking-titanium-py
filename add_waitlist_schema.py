import asyncio
from app.core.logging import setup_logging

async def run():
    setup_logging()
    await db_client.connect()
    
    async with db_client.pool.acquire() as conn:
        print("Adding waitlist config to providers...")
        await conn.execute("""
            ALTER TABLE providers
            ADD COLUMN IF NOT EXISTS waitlist_batch_size INT DEFAULT 3,
            ADD COLUMN IF NOT EXISTS waitlist_delay_minutes INT DEFAULT 15;
        """)

        print("Creating waitlist table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS waitlist (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id BIGINT NOT NULL REFERENCES users(id),
                provider_id UUID NOT NULL REFERENCES providers(id),
                status VARCHAR(50) DEFAULT 'ACTIVE', -- ACTIVE, FULFILLED, CANCELLED
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE (user_id, provider_id, status)
            );
        """)

        print("Creating waitlist_notifications table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS waitlist_notifications (
                id SERIAL PRIMARY KEY,
                waitlist_id UUID NOT NULL REFERENCES waitlist(id) ON DELETE CASCADE,
                slot_id UUID NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
                notified_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE (waitlist_id, slot_id)
            );
        """)

        # Also add this schema to connection.py so it's created automatically for new deployments
        print("Schema updated successfully.")
        
    await db_client.disconnect()

if __name__ == "__main__":
    asyncio.run(run())
