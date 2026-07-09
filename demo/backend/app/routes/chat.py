from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas import ChatRequest, ChatResponse
from app.services.agent_service import AgentService, AgentServiceError


router = APIRouter(prefix="/api", tags=["chat"])
agent_service = AgentService()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        return await run_in_threadpool(agent_service.ask, request.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _ndjson(events: Iterator[dict]) -> Iterator[str]:
    for event in events:
        yield json.dumps(event, ensure_ascii=False, default=str) + "\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question is required")

    return StreamingResponse(
        _ndjson(agent_service.stream_events(request.question)),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
