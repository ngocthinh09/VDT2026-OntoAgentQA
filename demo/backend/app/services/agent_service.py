from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from app.config import PROJECT_ROOT, get_settings, load_environment
from app.schemas import ChatMetadata, ChatResponse
from app.services.trace import make_json_safe, normalize_trace_steps


class AgentServiceError(RuntimeError):
    """Raised when the underlying QA agent cannot complete a request."""


def _ensure_project_root_on_path() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


@lru_cache(maxsize=4)
def _build_agent(
    max_iterations: int,
    temperature: float,
    max_tokens: int | None,
) -> Any:
    load_environment()
    _ensure_project_root_on_path()

    from agents.ontology_qa_agent import build_ontology_qa_agent

    return build_ontology_qa_agent(
        max_iterations=max_iterations,
        temperature=temperature,
        max_tokens=max_tokens,
    )


class AgentService:
    def _get_graph(self) -> Any:
        settings = get_settings()
        return _build_agent(
            settings.agent_max_iterations,
            settings.agent_temperature,
            settings.agent_max_tokens,
        )

    def _make_response(
        self,
        *,
        started_at: float,
        event_count: int,
        trace: list[Any],
        final_payload: dict[str, Any],
        generated_sparqls: list[str],
        last_execution_result: Any | None,
    ) -> ChatResponse:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        answer = str(final_payload.get("answer") or "").strip()
        if not answer:
            answer = "No answer was produced."

        sparql = final_payload.get("final_sparql") or (
            generated_sparqls[-1] if generated_sparqls else None
        )
        raw_result = make_json_safe(final_payload.get("result"))
        if raw_result is None:
            raw_result = last_execution_result

        finalization_error = final_payload.get("finalization_error")
        return ChatResponse(
            answer=answer,
            trace=trace,
            sparql=str(sparql) if sparql else None,
            raw_result=raw_result,
            metadata=ChatMetadata(
                elapsed_ms=elapsed_ms,
                event_count=event_count,
                finalization_error=str(finalization_error)
                if finalization_error
                else None,
            ),
        )

    def ask(self, question: str) -> ChatResponse:
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("question is required")

        graph = self._get_graph()

        started_at = time.perf_counter()
        trace = []
        event_count = 0
        final_payload: dict[str, Any] = {}
        generated_sparqls: list[str] = []
        last_execution_result: Any | None = None

        try:
            for event in graph.stream(
                {"question": clean_question, "options": []},
                stream_mode="updates",
            ):
                event_count += 1
                if not isinstance(event, dict):
                    continue

                for node_name, update in event.items():
                    if not isinstance(update, dict):
                        continue

                    raw_steps = update.get("steps") or []
                    if raw_steps:
                        trace.extend(
                            normalize_trace_steps(
                                raw_steps,
                                start_index=len(trace) + 1,
                            )
                        )

                    for query in update.get("generated_sparqls") or []:
                        if query:
                            generated_sparqls.append(str(query))

                    if "last_execution_result" in update:
                        last_execution_result = make_json_safe(
                            update.get("last_execution_result")
                        )

                    if node_name == "finalize" or any(
                        key in update
                        for key in (
                            "answer",
                            "final_sparql",
                            "result",
                            "finalization_error",
                        )
                    ):
                        final_payload.update(update)
        except Exception as exc:
            raise AgentServiceError(f"Ontology QA agent failed: {exc}") from exc

        return self._make_response(
            started_at=started_at,
            event_count=event_count,
            trace=trace,
            final_payload=final_payload,
            generated_sparqls=generated_sparqls,
            last_execution_result=last_execution_result,
        )

    def stream_events(self, question: str) -> Iterator[dict[str, Any]]:
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("question is required")

        started_at = time.perf_counter()
        trace = []
        event_count = 0
        final_payload: dict[str, Any] = {}
        generated_sparqls: list[str] = []
        last_execution_result: Any | None = None

        yield {
            "event": "run_started",
            "question": clean_question,
        }

        try:
            graph = self._get_graph()

            for event in graph.stream(
                {"question": clean_question, "options": []},
                stream_mode="updates",
            ):
                event_count += 1
                if not isinstance(event, dict):
                    continue

                for node_name, update in event.items():
                    if not isinstance(update, dict):
                        continue

                    raw_steps = update.get("steps") or []
                    if raw_steps:
                        steps = normalize_trace_steps(
                            raw_steps,
                            start_index=len(trace) + 1,
                        )
                        trace.extend(steps)
                        for step in steps:
                            yield {
                                "event": "trace_step",
                                "step": make_json_safe(step),
                            }

                    for query in update.get("generated_sparqls") or []:
                        if query:
                            generated_sparqls.append(str(query))

                    if "last_execution_result" in update:
                        last_execution_result = make_json_safe(
                            update.get("last_execution_result")
                        )

                    if node_name == "finalize" or any(
                        key in update
                        for key in (
                            "answer",
                            "final_sparql",
                            "result",
                            "finalization_error",
                        )
                    ):
                        final_payload.update(update)

            response = self._make_response(
                started_at=started_at,
                event_count=event_count,
                trace=trace,
                final_payload=final_payload,
                generated_sparqls=generated_sparqls,
                last_execution_result=last_execution_result,
            )
            yield {
                "event": "final_answer",
                "answer": response.answer,
                "sparql": response.sparql,
                "raw_result": response.raw_result,
                "metadata": make_json_safe(response.metadata),
            }
        except Exception as exc:
            yield {
                "event": "error",
                "message": f"Ontology QA agent failed: {exc}",
            }

        yield {"event": "done"}
