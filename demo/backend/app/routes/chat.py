from __future__ import annotations

from fastapi import APIRouter, HTTPException
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

