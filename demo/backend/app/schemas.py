from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class TraceStep(BaseModel):
    step: int
    type: str
    tool: str | None = None
    input: Any | None = None
    output: Any | None = None
    duration_ms: int | None = None
    status: str = "success"
    error: str | None = None


class ChatMetadata(BaseModel):
    elapsed_ms: int
    event_count: int
    finalization_error: str | None = None


class ChatResponse(BaseModel):
    answer: str
    trace: list[TraceStep]
    sparql: str | None = None
    raw_result: Any | None = None
    metadata: ChatMetadata

