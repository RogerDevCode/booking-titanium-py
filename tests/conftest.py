from app.core.config import settings
import pytest_asyncio
import os
from app.container import build_container

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.protocols import (
    DatabaseClientProtocol, RedisClientProtocol, BookingRepositoryProtocol,
    BookingServiceProtocol, UserServiceProtocol, TelegramSenderProtocol,
    AIServiceProtocol, RAGServiceProtocol, ConversationTransactionProtocol,
    SlotEngineProtocol, NotificationServiceProtocol, GCalServiceProtocol,
    AuthServiceProtocol
)
from app.container import Container
from app.pipeline.preprocessor import MessagePreprocessor
from app.pipeline.classifier import IntentClassifier
from app.fsm.main import FSMRouter
from app.services.booking_service import BookingService
from app.db.repositories.booking_repo import BookingRepository
from app.telegram.sender import TelegramSender

@pytest.fixture
def fake_db() -> AsyncMock:
    db = AsyncMock(spec=DatabaseClientProtocol)
    db.fetch.return_value = []
    db.fetchrow.return_value = None
    db.execute.return_value = "INSERT 0 1"
    
    # Mocking transaction context manager
    tx_mock = AsyncMock()
    tx_mock.__aenter__.return_value = None
    tx_mock.__aexit__.return_value = None
    db.transaction.return_value = tx_mock
    
    # Mocking acquire
    conn_mock = AsyncMock()
    acquire_mock = AsyncMock()
    acquire_mock.__aenter__.return_value = conn_mock
    acquire_mock.__aexit__.return_value = None
    if not hasattr(db, 'pool') or db.pool is None:
        db.pool = MagicMock()
    db.pool.acquire.return_value = acquire_mock
    
    return db

@pytest.fixture
def fake_redis() -> AsyncMock:
    redis = AsyncMock(spec=RedisClientProtocol)
    redis.client = AsyncMock()
    return redis

@pytest.fixture
def fake_sender() -> AsyncMock:
    sender = AsyncMock(spec=TelegramSenderProtocol)
    sender.build_inline_keyboard = TelegramSender.build_inline_keyboard
    sender.build_paginated_keyboard = TelegramSender.build_paginated_keyboard
    return sender

@pytest.fixture
def fake_booking_repo(fake_db) -> BookingRepositoryProtocol:
    return BookingRepository(db=fake_db)

@pytest.fixture
def fake_booking_service(fake_booking_repo) -> BookingServiceProtocol:
    return BookingService(repo=fake_booking_repo)

@pytest.fixture
def fake_user_service() -> AsyncMock:
    return AsyncMock(spec=UserServiceProtocol)

@pytest.fixture
def fake_notification_service() -> AsyncMock:
    return AsyncMock(spec=NotificationServiceProtocol)

@pytest.fixture
def fake_slot_engine() -> AsyncMock:
    return AsyncMock(spec=SlotEngineProtocol)

@pytest.fixture
def fake_ai_service() -> AsyncMock:
    return AsyncMock(spec=AIServiceProtocol)

@pytest.fixture
def fake_rag_service() -> AsyncMock:
    return AsyncMock(spec=RAGServiceProtocol)

@pytest.fixture
def fake_gcal_service() -> AsyncMock:
    return AsyncMock(spec=GCalServiceProtocol)

@pytest.fixture
def fake_auth_service() -> AsyncMock:
    return AsyncMock(spec=AuthServiceProtocol)

@pytest.fixture
def fake_conversation_tx() -> AsyncMock:
    return AsyncMock(spec=ConversationTransactionProtocol)

@pytest.fixture
def fake_container(
    fake_db, fake_redis, fake_sender, fake_booking_repo,
    fake_conversation_tx, fake_booking_service, fake_user_service,
    fake_notification_service, fake_slot_engine, fake_ai_service,
    fake_rag_service, fake_gcal_service, fake_auth_service
) -> Container:
    prep = MessagePreprocessor()
    clsf = IntentClassifier()
    
    router = FSMRouter(
        booking_service=fake_booking_service,
        user_service=fake_user_service,
        sender=fake_sender,
        booking_repo=fake_booking_repo,
        db=fake_db
    )

    return Container(
        settings=settings,
        db_client=fake_db,
        redis_client=fake_redis,
        telegram_sender=fake_sender,
        booking_repo=fake_booking_repo,
        conversation_tx=fake_conversation_tx,
        booking_service=fake_booking_service,
        user_service=fake_user_service,
        notification_service=fake_notification_service,
        slot_engine=fake_slot_engine,
        preprocessor=prep,
        classifier=clsf,
        fsm_router=router,
        ai_service=fake_ai_service,
        rag_service=fake_rag_service,
        gcal_service=fake_gcal_service,
        auth_service=fake_auth_service
    )


@pytest_asyncio.fixture(scope='function')
async def integration_container():
    # Use standard docker db ports for integration testing locally
    settings.DATABASE_URL = os.getenv('TEST_DATABASE_URL', 'postgresql://booking:booking@localhost:5432/booking')
    settings.REDIS_URL = os.getenv('TEST_REDIS_URL', 'redis://localhost:6379')
    
    container = build_container()
    await container.db_client.connect()
    await container.redis_client.connect()
    
    # Run the schema creation from master migrations
    migrations = [
        'db/migrations/001_schema.sql',
        'db/migrations/002_rls_policies.sql',
        'db/migrations/003_functions.sql',
        'db/migrations/005_provider_gcal.sql',
        'db/migrations/006_web_auth.sql',
        'db/migrations/007_provider_noshow_config.sql'
    ]
    async with container.db_client._pool.acquire() as conn: # type: ignore
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for migration_path in migrations:
            with open(migration_path, 'r') as sql_file:
                sql_content = sql_file.read()
                await conn.execute(sql_content)
        
    yield container
    
    await container.redis_client.disconnect()
    await container.db_client.disconnect()

@pytest_asyncio.fixture(scope='function')
async def clean_db_and_redis(integration_container):
    # Truncate tables and flush redis
    async with integration_container.db_client._pool.acquire() as conn: # type: ignore
        await conn.execute("""
            TRUNCATE TABLE 
                outbox_messages, 
                waitlist_notifications,
                waitlist,
                bookings,
                slots,
                users,
                conversation_states,
                knowledge_base,
                provider_schedules,
                provider_exceptions
            CASCADE;
        """)
        
    await integration_container.redis_client.client.flushdb()
    yield

