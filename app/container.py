import dataclasses
from app.core.config import Settings, settings

from app.domain.protocols import (
    DatabaseClientProtocol,
    RedisClientProtocol,
    TelegramSenderProtocol,
    BookingRepositoryProtocol,
    BookingServiceProtocol,
    UserServiceProtocol,
    NotificationServiceProtocol,
    SlotEngineProtocol,
    AIServiceProtocol,
    RAGServiceProtocol,
    ConversationTransactionProtocol
)
from app.pipeline.preprocessor import MessagePreprocessor
from app.pipeline.classifier import IntentClassifier
from app.fsm.main import FSMRouter

@dataclasses.dataclass(slots=True, frozen=True)
class Container:
    settings: Settings
    db_client: DatabaseClientProtocol
    redis_client: RedisClientProtocol
    telegram_sender: TelegramSenderProtocol
    
    booking_repo: BookingRepositoryProtocol
    conversation_tx: ConversationTransactionProtocol
    
    booking_service: BookingServiceProtocol
    user_service: UserServiceProtocol
    notification_service: NotificationServiceProtocol
    slot_engine: SlotEngineProtocol
    ai_service: AIServiceProtocol
    rag_service: RAGServiceProtocol
    
    preprocessor: MessagePreprocessor
    classifier: IntentClassifier
    
    fsm_router: FSMRouter

def build_container(s: Settings = settings) -> Container:
    from app.db.connection import DatabaseClient
    from app.db.redis_client import RedisClient
    from app.telegram.sender import TelegramSender
    from app.db.repositories.booking_repo import BookingRepository
    from app.db.conversation_tx import ConversationTransaction
    from app.services.booking_service import BookingService
    from app.services.user_service import UserService
    from app.services.notification_service import NotificationService
    from app.services.slot_engine import SlotEngine
    from app.services.ai_service import AIService
    from app.services.rag_service import RAGService
    from app.core.circuit_breaker import RedisCircuitBreaker

    db = DatabaseClient(s.DATABASE_URL, s.DATABASE_POOL)
    redis = RedisClient(s.REDIS_URL)
    
    sender = TelegramSender(db=db, token=s.TELEGRAM_BOT_TOKEN)
    
    b_repo = BookingRepository(db=db)
    conv_tx = ConversationTransaction(db=db)
    
    b_svc = BookingService(repo=b_repo)
    u_svc = UserService(db=db)
    n_svc = NotificationService(db=db, sender=sender)
    s_eng = SlotEngine(db=db)
    llm_cb = RedisCircuitBreaker(redis_client=redis, name="llm", failure_threshold=3, recovery_timeout=60)
    ai_svc = AIService(circuit_breaker=llm_cb)
    rag_svc = RAGService(db=db)
    
    prep = MessagePreprocessor()
    clsf = IntentClassifier()
    
    router = FSMRouter(
        booking_service=b_svc,
        user_service=u_svc,
        sender=sender,
        booking_repo=b_repo,
        db=db
    )
    
    return Container(
        settings=s,
        db_client=db,
        redis_client=redis,
        telegram_sender=sender,
        booking_repo=b_repo,
        conversation_tx=conv_tx,
        booking_service=b_svc,
        user_service=u_svc,
        notification_service=n_svc,
        ai_service=ai_svc,
        rag_service=rag_svc,
        slot_engine=s_eng,
        preprocessor=prep,
        classifier=clsf,
        fsm_router=router
    )
