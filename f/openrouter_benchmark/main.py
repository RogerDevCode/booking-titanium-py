# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "httpx>=0.28.1",
#   "pydantic>=2.10.0",
#   "email-validator>=2.2.0",
#   "asyncpg>=0.30.0",
#   "cryptography>=48.0.0",
#   "beartype>=0.19.0",
#   "returns>=0.24.0",
#   "redis>=7.4.0",
#   "typing-extensions>=4.12.0"
# ]
# ///
import asyncio

# ============================================================================
# PRE-FLIGHT CHECKLIST
# Mission         : Benchmark OpenRouter free models for NLU classification
# DB Tables Used  : NONE
# Concurrency Risk: NO — sequential calls
# GCal Calls      : NO
# Idempotency Key : N/A
# RLS Tenant ID   : NO
# Pydantic Schemas: YES — OpenRouterResponse validation
# ============================================================================
import os
import traceback
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel

from ..internal._wmill_adapter import get_variable, log
from ._benchmark_logic import MODELS, TASKS, run_benchmark_task
from ._benchmark_models import BenchmarkReport, ModelSummary, ModelTestResult

MODULE = "openrouter_benchmark"


async def _main_async(args: dict[str, Any] | None = None) -> BenchmarkReport:
    if args is None:
        args = {}
    api_key = get_variable("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not configured")

    summaries: list[ModelSummary] = []

    for model in MODELS:
        results: list[ModelTestResult] = []

        for task in TASKS:
            try:
                res = await run_benchmark_task(api_key, model, task)
                results.append(res)
            except Exception as err:
                log(f"Benchmark task {task['name']} failed for model {model['name']}", error=str(err), module=MODULE)
                results.append(
                    {
                        "model": model["name"],
                        "taskId": task["name"],
                        "success": False,
                        "rawResponse": None,
                        "parsed": None,
                        "error": str(err),
                        "correct": False,
                        "latencyMs": 0,
                        "totalTokens": None,
                    }
                )

        passed = len([r for r in results if r["success"]])
        failed = len(results) - passed
        correct = len([r for r in results if r["correct"]])
        avg_latency = int(sum(r["latencyMs"] for r in results) / len(results)) if results else 0

        summaries.append(
            {
                "model": model["name"],
                "totalTasks": len(results),
                "passed": passed,
                "failed": failed,
                "correct": correct,
                "avgLatencyMs": avg_latency,
                "results": results,
            }
        )

    report: BenchmarkReport = {
        "timestamp": datetime.now().isoformat(),
        "modelsTested": len(summaries),
        "summaries": summaries,
    }

    return report


def main(args: dict[str, Any]) -> dict[str, object]:
    try:
        result: Any = asyncio.run(_main_async(args))

        if isinstance(result, BaseModel):
            return cast("dict[str, object]", result.model_dump())
        return cast("dict[str, object]", result)

    except Exception as e:
        tb = traceback.format_exc()
        try:
            from ..internal._wmill_adapter import log

            log("CRITICAL_ENTRYPOINT_ERROR", error=str(e), traceback=tb, module=MODULE)
        except Exception:
            print(f"CRITICAL ERROR in {__file__}: {e}\n{tb}")

        raise RuntimeError(f"Execution failed: {e}") from e
