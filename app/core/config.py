from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    DATABASE_URL: str
    DATABASE_POOL: int = 10

    # Redis
    REDIS_URL: str = "redis://redis:6379"
    REDIS_PASSWORD: Optional[str] = None

    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ID: int

    # AI APIs
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    GOOGLE_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None

    # Google Calendar API
    GCALENDAR_CLIENT_ID: Optional[str] = None
    GCALENDAR_CLIENT_SECRET: Optional[str] = None
    GCALENDAR_API_KEY: Optional[str] = None

    # Worker
    WORKER_TIMEOUT: int = 1800
    
    # JWT Auth
    JWT_SECRET: str = "super-secret-titanium-key-123456!"

    # Logging
    LOG_LEVEL: str = "INFO"

settings = Settings() # type: ignore
