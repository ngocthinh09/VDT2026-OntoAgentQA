from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import chat, health


def create_app() -> FastAPI:
    settings = get_settings()
    allow_all_origins = "*" in settings.cors_origins

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all_origins else list(settings.cors_origins),
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chat.router)
    return app


app = create_app()

