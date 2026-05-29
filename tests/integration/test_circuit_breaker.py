import pytest
import asyncio
from unittest.mock import patch
from app.core.circuit_breaker import CircuitBreakerOpenException


@pytest.mark.asyncio
async def test_llm_circuit_breaker_trips_and_recovers(integration_container, clean_db_and_redis):
    """
    Tests that the Circuit Breaker trips after 3 consecutive network failures (timeouts),
    rejects immediate subsequent calls without network, and eventually transitions 
    to HALF-OPEN after the recovery timeout.
    """
    # 1. Force the litellm call to raise a TimeoutError
    with patch("app.services.ai_service.litellm.acompletion") as mock_acompletion:
        mock_acompletion.side_effect = asyncio.TimeoutError("Fake Network Timeout")

        # Fallo 1
        with pytest.raises(asyncio.TimeoutError):
            await integration_container.ai_service.get_response("Hola")
            
        # Fallo 2
        with pytest.raises(asyncio.TimeoutError):
            await integration_container.ai_service.get_response("Hola")
            
        # Fallo 3 (Umbral alcanzado, el circuito se ABRE)
        with pytest.raises(asyncio.TimeoutError):
            await integration_container.ai_service.get_response("Hola")

        # 2. La 4ta llamada debe rechazar INSTANTANEAMENTE con CircuitBreakerOpenException
        # Y mock_acompletion NO debe ser llamado de nuevo
        mock_acompletion.reset_mock()
        
        with pytest.raises(CircuitBreakerOpenException) as exc:
            await integration_container.ai_service.get_response("Hola")
            
        assert "Circuit llm is OPEN" in str(exc.value)
        mock_acompletion.assert_not_called()

        # 3. Simulate time passing (fast-forward recovery timeout)
        # We manually modify the last_failure in Redis to be 65 seconds ago
        import time
        past_time = time.time() - 65
        await integration_container.redis_client.client.set("cb:llm:last_failure", str(past_time))

        # 4. Now the circuit should be HALF-OPEN and allow one request through
        # If it succeeds, it closes. Let's make it succeed.
        class MockResponse:
            class MockChoice:
                class MockMessage:
                    content = "Mock success"
                message = MockMessage()
            choices = [MockChoice()]
            
        mock_acompletion.side_effect = None
        mock_acompletion.return_value = MockResponse()

        res = await integration_container.ai_service.get_response("Hola")
        assert res == "Mock success"

        # 5. Circuit is CLOSED now, verify it allows subsequent requests
        res = await integration_container.ai_service.get_response("Hola de nuevo")
        assert res == "Mock success"
        assert mock_acompletion.call_count == 2
