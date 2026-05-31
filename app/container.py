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
    ConversationTransactionProtocol,
    GCalServiceProtocol,
    AuthServiceProtocol,
    ConversationLoggerProtocol,
    NoteRepositoryProtocol,
    NoteServiceProtocol
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
    conversation_logger: ConversationLoggerProtocol
    note_repo: NoteRepositoryProtocol
    
    booking_service: BookingServiceProtocol
    user_service: UserServiceProtocol
    notification_service: NotificationServiceProtocol
    slot_engine: SlotEngineProtocol
    ai_service: AIServiceProtocol
    rag_service: RAGServiceProtocol
    gcal_service: GCalServiceProtocol
    auth_service: AuthServiceProtocol
    note_service: NoteServiceProtocol
    
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
    
    from app.db.repositories.conversation_repo import ConversationRepository
    conv_logger = ConversationRepository(db=db)
    
    from app.db.repositories.note_repo import NoteRepository
    note_rep = NoteRepository(db=db)
    
    b_svc = BookingService(repo=b_repo)
    u_svc = UserService(db=db)
    n_svc = NotificationService(db=db, sender=sender)
    s_eng = SlotEngine(db=db)
    llm_cb = RedisCircuitBreaker(redis_client=redis, name="llm", failure_threshold=3, recovery_timeout=60)
    ai_svc = AIService(circuit_breaker=llm_cb)
    rag_svc = RAGService(db=db)
    
    from app.services.gcal_service import GCalService
    gcal_svc = GCalService(db=db, settings=s)
    
    from app.services.auth_service import AuthService
    auth_svc = AuthService(db=db, settings=s)
    
    from app.services.note_service import NoteService
    note_svc = NoteService(repo=note_rep)
    
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
        conversation_logger=conv_logger,
        note_repo=note_rep,
        booking_service=b_svc,
        user_service=u_svc,
        notification_service=n_svc,
        ai_service=ai_svc,
        rag_service=rag_svc,
        gcal_service=gcal_svc,
        auth_service=auth_svc,
        note_service=note_svc,
        slot_engine=s_eng,
        preprocessor=prep,
        classifier=clsf,
        fsm_router=router
    )
