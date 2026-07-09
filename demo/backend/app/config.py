from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository root that contains the existing agent package."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "agents" / "ontology_qa_agent.py").exists():
            return candidate
    raise RuntimeError("Could not find project root containing agents/ontology_qa_agent.py")


PROJECT_ROOT = find_project_root()
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def load_environment() -> None:
    """Load root and demo backend environment files.

    The root `.env` remains the canonical configuration for the agent. A local
    `demo/backend/.env` can override values for demo-specific settings.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(BACKEND_ROOT / ".env", override=True)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _int_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _optional_int_env(name: str) -> int | None:
    raw_value = os.environ.get(name)
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    app_name: str
    cors_origins: tuple[str, ...]
    agent_max_iterations: int
    agent_temperature: float
    agent_max_tokens: int | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_environment()
    return Settings(
        app_name=os.environ.get("DEMO_APP_NAME", "OntoAgentQA Demo API"),
        cors_origins=_split_csv(
            os.environ.get(
                "DEMO_CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            )
        ),
        agent_max_iterations=_int_env("DEMO_AGENT_MAX_ITERATIONS", 15),
        agent_temperature=_float_env("DEMO_AGENT_TEMPERATURE", 0.0),
        agent_max_tokens=_optional_int_env("DEMO_AGENT_MAX_TOKENS"),
    )

