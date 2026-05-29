from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict


class ModelCandidate(TypedDict):
    id: str
    name: str


class NLUIntent(BaseModel):
    intent: str
    confidence: float
    requires_human: bool


class ModelTestResult(TypedDict):
    model: str
    taskId: str
    success: bool
    rawResponse: str | None
    parsed: dict[str, Any] | None
    error: str | None
    correct: bool | None
    latencyMs: int
    totalTokens: int | None


class ModelSummary(TypedDict):
    model: str
    totalTasks: int
    passed: int
    failed: int
    correct: int
    avgLatencyMs: int
    results: list[ModelTestResult]


class BenchmarkReport(TypedDict):
    timestamp: str
    modelsTested: int
    summaries: list[ModelSummary]


class TaskPrompt(TypedDict):
    name: str
    userMessage: str
    expectedIntent: str
    expectedHuman: bool


class OpenRouterUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenRouterChoiceMessage(BaseModel):
    content: str
    role: str | None = None


class OpenRouterChoice(BaseModel):
    message: OpenRouterChoiceMessage
    finish_reason: str | None = None


class OpenRouterResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: str | None = None
    choices: list[OpenRouterChoice]
    usage: OpenRouterUsage | None = None
