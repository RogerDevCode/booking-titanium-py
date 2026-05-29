import json
import re
import time
from typing import Any, cast

import httpx

from ._benchmark_models import ModelCandidate, ModelTestResult, NLUIntent, OpenRouterResponse, TaskPrompt

MODELS: list[ModelCandidate] = [
    {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini 2.0 Flash (free)"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (free)"},
    {"id": "mistralai/mistral-small-3.1-24b-instruct:free", "name": "Mistral Small 3.1 24B (free)"},
    {"id": "qwen/qwen3-32b:free", "name": "Qwen3 32B (free)"},
    {"id": "openrouter/auto:free", "name": "OpenRouter Auto (free router)"},
]

TASKS: list[TaskPrompt] = [
    {
        "name": "create_cita",
        "userMessage": "Hola, quiero agendar una cita para la próxima semana con el doctor García.",
        "expectedIntent": "crear_cita",
        "expectedHuman": False,
    },
    {
        "name": "urgencia_medica",
        "userMessage": "Tengo un dolor muy fuerte en el pecho y me cuesta respirar, ayúdenme!",
        "expectedIntent": "fuera_de_contexto",
        "expectedHuman": True,
    },
]

SYSTEM_PROMPT = """Eres el Motor de Enrutamiento NLU de un SaaS médico.
Tu ÚNICA salida permitida es un objeto JSON puro con estas claves:
{"intent":"<intent>","confidence":<0.0-1.0>,"requires_human":<true/false>}

VALORES VÁLIDOS PARA "intent":
  "crear_cita", "cancelar_cita", "reagendar_cita", "ver_disponibilidad", "mis_citas", "duda_general", "fuera_de_contexto"  # noqa: E501
"""  # noqa: E501


def extract_json(text: str) -> dict[str, Any] | None:
    try:
        return cast("dict[str, Any]", json.loads(text))
    except Exception as e:
        from ..internal._wmill_adapter import log

        log("SILENT_ERROR_CAUGHT", error=str(e), file="_benchmark_logic.py")
        pass

    # Try markdown fences
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            return cast("dict[str, Any]", json.loads(match.group(1)))
        except Exception as e:
            from ..internal._wmill_adapter import log

            log("SILENT_ERROR_CAUGHT", error=str(e), file="_benchmark_logic.py")
            pass

    # Try simple brace search
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return cast("dict[str, Any]", json.loads(match.group(1)))
        except Exception as e:
            from ..internal._wmill_adapter import log

            log("SILENT_ERROR_CAUGHT", error=str(e), file="_benchmark_logic.py")
            pass

    return None


async def run_benchmark_task(api_key: str, model: ModelCandidate, task: TaskPrompt) -> ModelTestResult:
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://localhost",
                    "X-Title": "Windmill NLU Benchmark",
                },
                json={
                    "model": model["id"],
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": task["userMessage"]},
                    ],
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
            )

            latency = int((time.time() - start_time) * 1000)

            if res.status_code != 200:
                raise RuntimeError(f"HTTP {res.status_code}: {res.text[:100]}")

            data = res.json()
            parsed_res = OpenRouterResponse.model_validate(data)
            content = parsed_res.choices[0].message.content
            usage = parsed_res.usage

            extracted = extract_json(content)
            correct = False
            parsed_intent = None
            error = None

            if extracted:
                try:
                    nlu = NLUIntent.model_validate(extracted)
                    parsed_intent = nlu.model_dump()
                    correct = nlu.intent == task["expectedIntent"] and nlu.requires_human == task["expectedHuman"]
                except Exception as e:
                    error = f"Schema mismatch: {e}"
            else:
                error = "JSON extraction failed"

            return {
                "model": model["name"],
                "taskId": task["name"],
                "success": True,
                "rawResponse": content,
                "parsed": parsed_intent,
                "error": error,
                "correct": correct,
                "latencyMs": latency,
                "totalTokens": usage.total_tokens if usage else None,
            }

    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(str(e)) from e
