import litellm
import asyncio
from typing import Optional
from app.core.config import settings
from app.core.logging import logger
from app.core.circuit_breaker import RedisCircuitBreaker, CircuitBreakerOpenException

class AIService:
    """
    Service for AI interactions (LLM).
    Uses LiteLLM to support multiple providers (OpenAI, Google, Groq, etc).
    """
    
    def __init__(self, circuit_breaker: RedisCircuitBreaker):
        self.model = settings.OPENAI_MODEL
        self.api_key = settings.OPENAI_API_KEY
        # Fallback to other keys if configured
        if not self.api_key and settings.GROQ_API_KEY:
            self.model = "groq/llama-3.1-70b-versatile"
            self.api_key = settings.GROQ_API_KEY
            
        self._cb = circuit_breaker

    async def _safe_litellm_call(self, user_text: str, context: Optional[str] = None) -> str:
        cb_state = await self._cb.get_state()
        if cb_state == "OPEN":
            raise CircuitBreakerOpenException(f"Circuit {self._cb.name} is OPEN")
            
        system_prompt = (
            "Eres el asistente experto de la Clínica Titanium. "
            "Tu misión es responder dudas de salud y administrativas con precisión y empatía. "
            "Usa el contexto proporcionado para responder. Si no sabes algo, sé honesto."
        )
        
        if context:
            system_prompt += f"\n\nContexto relevante:\n{context}"

        try:
            # Timeout estricto de 3 segundos para el LLM para evitar encolamiento masivo
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    api_key=self.api_key,
                    temperature=0.3
                ),
                timeout=3.0
            )
            await self._cb.record_success()
            return response.choices[0].message.content # type: ignore
        except Exception as e:
            await self._cb.record_failure()
            raise

    async def get_response(self, user_text: str, context: Optional[str] = None) -> str:
        if not self.api_key:
            return "Lo siento, mi cerebro (API Key) no está configurado. Por favor contacta al administrador."

        try:
            return await self._safe_litellm_call(user_text, context)
        except CircuitBreakerOpenException:
            # Re-raise so the caller can handle the fallback (e.g., FSM or Pipeline)
            raise
        except Exception as e:
            logger.error("AI completion failed", error=str(e))
            # No ocultamos la excepción aquí, la lanzamos para que el CB cuente el fallo
            raise

# Temporary fallback
from app.db.redis_client import redis_client
llm_cb = RedisCircuitBreaker(redis_client=redis_client, name="llm", failure_threshold=3, recovery_timeout=60)
ai_service = AIService(circuit_breaker=llm_cb)
