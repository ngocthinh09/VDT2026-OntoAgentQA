from __future__ import annotations

import argparse
import csv
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from openai import OpenAI

from .sparql_gen import (
    ONTOLOGY_HINTS,
    LLMCallRecord,
    QuestionCase,
    add_missing_common_prefixes,
    build_benchmark_prompt,
    build_extra_body,
    build_repository_url_from_env,
    extract_answer,
    extract_json_object,
    find_project_root,
    format_graphdb_result,
    has_db_evidence,
    has_graphdb_result,
    is_read_only_sparql,
    load_questions,
    parse_bool,
    strip_answer_options,
    summarize_graphdb_result,
    system_message,
    usage_int,
    user_message,
)


FRIEND_REPO_COMMIT = "d186e3d"


@dataclass(frozen=True)
class SparqlSelfCorrectConfig:
    project_root: Path
    csv_path: Path
    env_path: Path
    output_root: Path
    model: str
    api_key: str
    graphdb_endpoint: str
    base_url: str = "https://openrouter.ai/api/v1"
    provider_only: str | None = None
    temperature: float = 0.2
    request_delay_seconds: float = 0.0
    graphdb_timeout_seconds: int = 200
    graphdb_max_rows: int = 20
    max_sparql_attempts: int = 5
    question_timeout_seconds: int = 1200
    finalization_reserve_seconds: int = 240

    @classmethod
    def from_project_root(cls, project_root: Path | None = None) -> "SparqlSelfCorrectConfig":
        root = find_project_root(project_root or Path.cwd())
        env_path = root / ".env"
        load_dotenv(env_path)

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        model = os.getenv("OPENROUTER_MODEL", "")
        graphdb_endpoint = (
            os.getenv("GRAPHDB_ENDPOINT")
            or os.getenv("GRAPHDB_REPOSITORY_URL")
            or build_repository_url_from_env()
        )
        if not api_key:
            raise RuntimeError("Missing OPENROUTER_API_KEY in .env")
        if not model:
            raise RuntimeError("Missing OPENROUTER_MODEL in .env")
        if not graphdb_endpoint:
            raise RuntimeError("Missing GRAPHDB_ENDPOINT or GRAPHDB_REPOSITORY_URL in .env")

        graphdb_timeout = os.getenv("GRAPHDB_TIMEOUT") or os.getenv("GRAPHDB_QUERY_TIMEOUT_SECONDS") or "200"

        return cls(
            project_root=root,
            csv_path=root / "data" / "ontologyqa_test_questions_v1.csv",
            env_path=env_path,
            output_root=root / "experiments" / "results" / "sparql_self_correct",
            model=model,
            api_key=api_key,
            graphdb_endpoint=graphdb_endpoint.rstrip("/"),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            provider_only=os.getenv("OPENROUTER_PROVIDER_ONLY") or None,
            temperature=float(os.getenv("CHAT_TEMPERATURE", "0.2")),
            request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "0")),
            graphdb_timeout_seconds=int(float(graphdb_timeout)),
            graphdb_max_rows=int(os.getenv("GRAPHDB_MAX_ROWS", "20")),
            max_sparql_attempts=int(os.getenv("MAX_SPARQL_ATTEMPTS", "5")),
            question_timeout_seconds=int(os.getenv("QUESTION_TIMEOUT_SECONDS", "1200")),
            finalization_reserve_seconds=int(os.getenv("QUESTION_FINALIZATION_RESERVE_SECONDS", "240")),
        )


@dataclass(frozen=True)
class PipelineOutput:
    final_response: str
    history: dict[str, Any]
    latest_graphdb_result_summary: dict[str, Any] | None
    latest_graphdb_error: str | None
    llm_calls: list[LLMCallRecord]
    latency_seconds: float


@dataclass(frozen=True)
class BenchmarkResult:
    run_id: str
    timestamp_utc: str
    source_repo_commit: str
    question_id: str
    question_type: str
    question: str
    correct_answer: int
    predicted_answer: int | None
    is_correct: bool
    has_db_evidence: bool
    valid_answer_count: int
    sparql_attempts: int
    status: str
    error_type: str | None
    error_message: str | None
    raw_response: str
    history: str
    latest_graphdb_result_summary: str
    latest_graphdb_error: str | None
    llm_calls: str
    model: str
    provider_only: str | None
    temperature: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    latency_seconds: float


class SparqlSelfCorrectRunner:
    def __init__(self, config: SparqlSelfCorrectConfig):
        self.config = config
        self.client = OpenAI(base_url=config.base_url, api_key=config.api_key)

    def complete(self, step: str, messages: list[dict[str, str]]) -> LLMCallRecord:
        request_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        extra_body = build_extra_body(self.config.provider_only)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        started = time.perf_counter()
        completion = self.client.chat.completions.create(**request_kwargs)
        latency = time.perf_counter() - started
        raw_response = completion.model_dump()
        content = completion.choices[0].message.content or ""
        usage = raw_response.get("usage") or {}
        input_tokens = usage_int(usage, "prompt_tokens", "input_tokens")
        output_tokens = usage_int(usage, "completion_tokens", "output_tokens")
        total_tokens = usage_int(usage, "total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return LLMCallRecord(
            step=step,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=usage.get("cost"),
            latency_seconds=latency,
        )

    @staticmethod
    def build_history(original_prompt: str) -> dict[str, Any]:
        return {"original_prompt": original_prompt, "steps": []}

    @staticmethod
    def add_history_step(history: dict[str, Any], step_type: str, payload: dict[str, Any]) -> None:
        steps = history.setdefault("steps", [])
        if isinstance(steps, list):
            steps.append({"type": step_type, **payload})

    @staticmethod
    def history_to_text(history: dict[str, Any]) -> str:
        return json.dumps(history, ensure_ascii=False, indent=2)

    def plan_graphdb_usage(self, message: str, calls: list[LLMCallRecord]) -> dict[str, Any]:
        lookup_prompt = strip_answer_options(message)
        prompt = (
            "You are the central routing agent for a Vietnamese chatbot backed by GraphDB/DBpedia.\n"
            "Decide whether the user's core question needs GraphDB lookup before answering.\n\n"
            "Important boundary: if the original prompt is multiple-choice, do not pass answer options or option IDs to the SPARQL coder. "
            "The SPARQL coder should only retrieve neutral facts needed to answer the core question. The central agent will compare facts with choices later.\n\n"
            "Use GraphDB for factual questions about entities, relationships, attributes, dates, places, people, organizations, "
            "classes, or multiple-choice questions that likely require stored knowledge.\n"
            "Do not use GraphDB for greetings, chitchat, writing/transformation tasks, pure math, or requests that can be answered "
            "without factual lookup.\n\n"
            "Return only valid JSON with this schema:\n"
            "{\"use_graphdb\":true,\"query_description\":\"neutral fact lookup description without answer options\",\"reason\":\"short reason\"}\n"
            "If GraphDB is not needed, set use_graphdb=false and query_description=\"\".\n\n"
            f"Original prompt:\n{message}\n\n"
            f"Core question without answer options:\n{lookup_prompt}"
        )
        call = self.complete(
            "central_route",
            [
                system_message("You are a central agent. Return only routing JSON."),
                user_message(prompt),
            ],
        )
        calls.append(call)
        data = extract_json_object(call.content)
        if not data:
            return {"use_graphdb": True, "query_description": lookup_prompt, "reason": "routing_json_parse_failed"}

        use_graphdb = parse_bool(data.get("use_graphdb"))
        query_description = strip_answer_options(str(data.get("query_description", "")).strip())
        if use_graphdb and not query_description:
            query_description = lookup_prompt

        return {
            "use_graphdb": use_graphdb,
            "query_description": query_description,
            "reason": str(data.get("reason", "")).strip(),
        }

    def decide_next_action(
        self,
        message: str,
        history: dict[str, Any],
        sparql_attempts: int,
        calls: list[LLMCallRecord],
    ) -> dict[str, Any]:
        if sparql_attempts >= self.config.max_sparql_attempts:
            return {
                "action": "answer",
                "query_description": "",
                "reason": "max_sparql_attempts_reached",
            }

        prompt = (
            "You are the central control agent for a Vietnamese chatbot backed by GraphDB/DBpedia.\n"
            "You can inspect the original user prompt and the full execution history.\n"
            "Decide whether the available information is enough to answer, or whether one more neutral GraphDB lookup is needed.\n\n"
            "Important rules:\n"
            "- If history contains enough concrete evidence or enough failed attempts to make progress unlikely, choose action=answer.\n"
            "- If one more lookup is useful, choose action=sparql and write a neutral query_description for the SPARQL coder.\n"
            "- Do not include answer option IDs or answer choices in query_description.\n"
            "- Avoid repeating failed or already-executed lookups from history.\n"
            "- Return only valid JSON with this schema: "
            "{\"action\":\"answer\",\"query_description\":\"\",\"reason\":\"short reason\"}.\n"
            "- action must be either answer or sparql.\n\n"
            f"SPARQL attempts used: {sparql_attempts}/{self.config.max_sparql_attempts}\n\n"
            f"Original prompt:\n{message}\n\n"
            f"Execution history:\n{self.history_to_text(history)}"
        )
        call = self.complete(
            "central_next_action",
            [
                system_message("You are a central control agent. Return only action JSON."),
                user_message(prompt),
            ],
        )
        calls.append(call)
        data = extract_json_object(call.content)
        action = str(data.get("action", "answer")).strip().lower() if data else "answer"
        if action not in {"answer", "sparql"}:
            action = "answer"

        query_description = strip_answer_options(str(data.get("query_description", "")).strip()) if data else ""
        if action == "sparql" and not query_description:
            action = "answer"

        return {
            "action": action,
            "query_description": query_description if action == "sparql" else "",
            "reason": str(data.get("reason", "")).strip() if data else "next_action_json_parse_failed",
        }

    def generate_sparql(self, user_prompt: str, query_description: str, calls: list[LLMCallRecord]) -> str:
        prompt = (
            "You are a SPARQL coder for the local GraphDB.\n"
            "Create one read-only SPARQL query from the central agent description.\n"
            "Only create SELECT or ASK. Do not use INSERT, DELETE, UPDATE, or SERVICE.\n"
            "Prefer returning neutral factual evidence: entities, relationships, labels, dates, counts, and literal values needed by the core question.\n"
            "When selecting resources, include rdfs:label values when available and prefer FILTER(lang(?label) = 'en').\n"
            "For entity lookup, use exact dbr:Entity_Name only when confident; otherwise search labels with CONTAINS(LCASE(STR(?label)), \"text\").\n"
            "Do not include answer choices, option IDs, VALUES blocks for choices, or BINDs mapping choices to options. The central agent handles choices later.\n"
            "SPARQL function syntax matters: use CONTAINS(LCASE(STR(?label)), \"text\"), never LCASE(STR(?label)) CONTAINS(\"text\").\n\n"
            "Common prefixes:\n"
            "PREFIX dbo: <http://dbpedia.org/ontology/>\n"
            "PREFIX dbr: <http://dbpedia.org/resource/>\n"
            "PREFIX dbp: <http://dbpedia.org/property/>\n"
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX foaf: <http://xmlns.com/foaf/0.1/>\n"
            "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n\n"
            f"Schema hints:\n{ONTOLOGY_HINTS}\n\n"
            "Return only valid JSON with this schema: {\"sparql\":\"...\"}.\n"
            "If a useful query cannot be created, return {\"sparql\":\"\"}.\n\n"
            f"Original user prompt, for context only; do not extract answer options from it:\n{user_prompt}\n\n"
            f"Central agent query description:\n{query_description}"
        )
        call = self.complete(
            "sparql_generate",
            [
                system_message("You are a SPARQL coder. Return only SPARQL JSON."),
                user_message(prompt),
            ],
        )
        calls.append(call)
        data = extract_json_object(call.content)
        sparql = str(data.get("sparql", "")).strip() if data else ""
        sparql = add_missing_common_prefixes(sparql)
        return sparql if is_read_only_sparql(sparql) else ""

    def effective_query_timeout_seconds(self, remaining_question_seconds: float, remaining_graphdb_queries: int) -> int:
        usable_seconds = int(remaining_question_seconds) - self.config.finalization_reserve_seconds
        if usable_seconds <= 0:
            return 0
        query_count = max(1, remaining_graphdb_queries)
        return max(1, min(self.config.graphdb_timeout_seconds, usable_seconds // query_count))

    def query_graphdb(self, sparql: str, timeout_seconds: int) -> dict[str, Any]:
        response = requests.post(
            self.config.graphdb_endpoint,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=(5, timeout_seconds),
        )
        response.raise_for_status()
        return response.json()

    def execute_sparql_step(
        self,
        message: str,
        history: dict[str, Any],
        query_description: str,
        attempt: int,
        graphdb_timeout_seconds: int,
        calls: list[LLMCallRecord],
    ) -> None:
        sparql = ""
        graphdb_result = None
        graphdb_error = None
        try:
            sparql = self.generate_sparql(message, query_description, calls)
            if sparql:
                graphdb_result = self.query_graphdb(sparql, graphdb_timeout_seconds)
            else:
                graphdb_error = "SPARQL_GENERATION_EMPTY_OR_REJECTED"
        except requests.Timeout:
            graphdb_error = "GRAPHDB_TIMEOUT: GraphDB query exceeded the configured timeout."
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            graphdb_error = f"GRAPHDB_ERROR: {type(exc).__name__}: {exc}"

        self.add_history_step(
            history,
            "sparql_execution",
            {
                "attempt": attempt,
                "query_description": query_description,
                "sparql": sparql,
                "graphdb_timeout_seconds": graphdb_timeout_seconds,
                "result": graphdb_result,
                "result_summary": summarize_graphdb_result(graphdb_result) if graphdb_result else None,
                "error": graphdb_error,
            },
        )

    @staticmethod
    def latest_graphdb_evidence(history: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        steps = history.get("steps", [])
        if not isinstance(steps, list):
            return None, None

        latest_error = None
        for step in reversed(steps):
            if not isinstance(step, dict) or step.get("type") != "sparql_execution":
                continue
            error = step.get("error")
            if error and not latest_error:
                latest_error = str(error)
            result = step.get("result")
            if isinstance(result, dict) and has_graphdb_result(result):
                return result, None
        return None, latest_error

    def normalize_answer_evidence_response(
        self,
        message: str,
        raw_text: str,
        graphdb_result: dict[str, Any] | None = None,
        graphdb_error: str | None = None,
    ) -> str:
        from .sparql_gen import is_multiple_choice_prompt

        if not is_multiple_choice_prompt(message):
            return raw_text

        data = extract_json_object(raw_text)
        answer = str(data.get("answer", "")).strip() if data else ""
        if not answer or answer not in {"1", "2", "3", "4", "5"}:
            return raw_text

        raw_evidence = data.get("evidence")
        evidence = [str(item).strip() for item in raw_evidence if str(item).strip()] if isinstance(raw_evidence, list) else []
        if not evidence:
            if graphdb_result and has_graphdb_result(graphdb_result):
                evidence = [f"SPARQL evidence: {format_graphdb_result(graphdb_result, self.config.graphdb_max_rows)}"]
            elif graphdb_error:
                evidence = [f"No usable SPARQL evidence ({graphdb_error}); selected as a best-effort guess."]
            else:
                evidence = ["No usable SPARQL evidence; selected as a best-effort guess."]

        return json.dumps({"answer": answer, "evidence": evidence}, ensure_ascii=False)

    def final_answer_messages(self, message: str, history: dict[str, Any]) -> list[dict[str, str]]:
        return [
            system_message(
                "You are the answer formatting agent for a Vietnamese chatbot. "
                "Use the original user prompt and execution history to produce the final user-facing answer. "
                "For multiple-choice prompts, always return only valid JSON with this schema: "
                "{\"answer\":\"1\",\"evidence\":[\"short evidence text\"]}. "
                "The answer value must be the selected option ID as a string. "
                "Evidence must be a JSON array of short strings. "
                "If GraphDB rows are available in history, compare those facts with the original choices and choose only the option supported by GraphDB evidence. "
                "Every evidence item should cite a concrete value, entity, relationship, date, count, or literal from the history when possible. "
                "If no usable SPARQL evidence exists after the central agent stopped, choose the most likely answer from general knowledge and say evidence is a best-effort fallback. "
                "For non-multiple-choice prompts, answer clearly and include GraphDB evidence when available."
            ),
            user_message(
                f"Original prompt including any answer choices:\n{message}\n\n"
                f"Execution history:\n{json.dumps(history, ensure_ascii=False, indent=2)}\n\n"
                "Return the final answer to the user."
            ),
        ]

    def format_final_answer(self, message: str, history: dict[str, Any], calls: list[LLMCallRecord]) -> str:
        call = self.complete("answer_formatter_final", self.final_answer_messages(message, history))
        calls.append(call)
        return call.content

    def run_pipeline(self, user_prompt: str) -> PipelineOutput:
        started = time.perf_counter()
        deadline = time.monotonic() + self.config.question_timeout_seconds
        calls: list[LLMCallRecord] = []
        history = self.build_history(user_prompt)
        routing_decision = self.plan_graphdb_usage(user_prompt, calls)
        self.add_history_step(history, "central_routing", routing_decision)

        sparql_attempts = 0
        if routing_decision["use_graphdb"]:
            query_description = routing_decision["query_description"]
            while sparql_attempts < self.config.max_sparql_attempts:
                sparql_attempts += 1
                remaining = max(0.0, deadline - time.monotonic())
                graphdb_timeout_seconds = self.effective_query_timeout_seconds(
                    remaining_question_seconds=remaining,
                    remaining_graphdb_queries=self.config.max_sparql_attempts - sparql_attempts + 1,
                )
                if graphdb_timeout_seconds <= 0:
                    self.add_history_step(
                        history,
                        "sparql_execution",
                        {
                            "attempt": sparql_attempts,
                            "query_description": query_description,
                            "sparql": "",
                            "graphdb_timeout_seconds": 0,
                            "result": None,
                            "result_summary": None,
                            "error": "QUESTION_TIMEOUT: skipped GraphDB to reserve time for final answer.",
                        },
                    )
                    break

                self.execute_sparql_step(
                    user_prompt,
                    history,
                    query_description,
                    sparql_attempts,
                    graphdb_timeout_seconds,
                    calls,
                )

                next_action = self.decide_next_action(user_prompt, history, sparql_attempts, calls)
                self.add_history_step(history, "central_next_action", next_action)

                if next_action["action"] != "sparql":
                    break
                query_description = next_action["query_description"]

        raw_answer = self.format_final_answer(user_prompt, history, calls)
        graphdb_result, graphdb_error = self.latest_graphdb_evidence(history)
        final_response = self.normalize_answer_evidence_response(user_prompt, raw_answer, graphdb_result, graphdb_error)

        return PipelineOutput(
            final_response=final_response,
            history=history,
            latest_graphdb_result_summary=summarize_graphdb_result(graphdb_result) if graphdb_result else None,
            latest_graphdb_error=graphdb_error,
            llm_calls=calls,
            latency_seconds=time.perf_counter() - started,
        )

    def run_case(self, run_id: str, case: QuestionCase) -> BenchmarkResult:
        user_prompt = build_benchmark_prompt(case)
        pipeline: PipelineOutput | None = None
        error: Exception | None = None
        try:
            pipeline = self.run_pipeline(user_prompt)
        except Exception as exc:
            error = exc

        raw_response = pipeline.final_response if pipeline else ""
        predicted = extract_answer(raw_response, len(case.options)) if error is None else None
        llm_calls = pipeline.llm_calls if pipeline else []
        input_tokens = sum(call.input_tokens or 0 for call in llm_calls)
        output_tokens = sum(call.output_tokens or 0 for call in llm_calls)
        total_tokens = sum(call.total_tokens or 0 for call in llm_calls)
        cost = sum(call.cost or 0.0 for call in llm_calls)
        history = pipeline.history if pipeline else {}
        sparql_attempts = sum(
            1 for step in history.get("steps", [])
            if isinstance(step, dict) and step.get("type") == "sparql_execution"
        )

        return BenchmarkResult(
            run_id=run_id,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            source_repo_commit=FRIEND_REPO_COMMIT,
            question_id=case.question_id,
            question_type=case.question_type,
            question=case.question,
            correct_answer=case.correct_answer,
            predicted_answer=predicted,
            is_correct=predicted == case.correct_answer,
            has_db_evidence=has_db_evidence(raw_response),
            valid_answer_count=len(case.options),
            sparql_attempts=sparql_attempts,
            status="error" if error else "success",
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
            raw_response=raw_response,
            history=json.dumps(history, ensure_ascii=False),
            latest_graphdb_result_summary=json.dumps(
                pipeline.latest_graphdb_result_summary if pipeline else None,
                ensure_ascii=False,
            ),
            latest_graphdb_error=pipeline.latest_graphdb_error if pipeline else None,
            llm_calls=json.dumps([asdict(call) for call in llm_calls], ensure_ascii=False),
            model=self.config.model,
            provider_only=self.config.provider_only,
            temperature=self.config.temperature,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            latency_seconds=pipeline.latency_seconds if pipeline else 0.0,
        )

    def run(
        self,
        *,
        limit: int = 0,
        offset: int = 0,
        save_incrementally: bool = True,
    ) -> tuple[list[BenchmarkResult], Path]:
        cases = load_questions(self.config.csv_path)
        if offset:
            cases = cases[offset:]
        if limit:
            cases = cases[:limit]
        if not cases:
            raise RuntimeError("No benchmark cases found")

        run_id = f"sparql-self-correct-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        output_dir = self.config.output_root / run_id
        results: list[BenchmarkResult] = []

        print(f"Run ID: {run_id}")
        print(f"Source commit: {FRIEND_REPO_COMMIT}")
        print(f"Cases: {len(cases)}")
        print(f"Model: {self.config.model}")
        print(f"Provider only: {self.config.provider_only}")
        print(f"GraphDB: {self.config.graphdb_endpoint}")
        print(f"Max SPARQL attempts: {self.config.max_sparql_attempts}")
        print(f"Output dir: {output_dir}")

        for index, case in enumerate(cases, start=1):
            result = self.run_case(run_id, case)
            results.append(result)
            print(
                f"[{index}/{len(cases)}] id={case.question_id} status={result.status} "
                f"pred={result.predicted_answer} correct={case.correct_answer} ok={result.is_correct} "
                f"attempts={result.sparql_attempts} db_evidence={result.has_db_evidence} "
                f"tokens={result.total_tokens} (in={result.input_tokens}, out={result.output_tokens}) "
                f"latency={result.latency_seconds:.2f}s"
            )
            if result.error_message:
                print(f"  error: {result.error_message}")

            if save_incrementally:
                write_outputs(results, output_dir)

            if self.config.request_delay_seconds > 0 and index < len(cases):
                time.sleep(self.config.request_delay_seconds)

        write_outputs(results, output_dir)
        return results, output_dir


def summarize(results: list[BenchmarkResult]) -> dict[str, Any]:
    successful = [result for result in results if result.status == "success"]
    total = len(results)
    correct = sum(result.is_correct for result in successful)
    db_evidence_count = sum(result.has_db_evidence for result in successful)

    def avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    by_type: dict[str, dict[str, Any]] = {}
    for result in successful:
        stats = by_type.setdefault(
            result.question_type or "unknown",
            {
                "total": 0,
                "correct": 0,
                "db_evidence_count": 0,
                "sparql_attempts_sum": 0,
                "input_tokens_sum": 0,
                "output_tokens_sum": 0,
                "total_tokens_sum": 0,
                "latency_seconds_sum": 0.0,
                "cost_sum": 0.0,
            },
        )
        stats["total"] += 1
        stats["correct"] += int(result.is_correct)
        stats["db_evidence_count"] += int(result.has_db_evidence)
        stats["sparql_attempts_sum"] += result.sparql_attempts
        stats["input_tokens_sum"] += result.input_tokens
        stats["output_tokens_sum"] += result.output_tokens
        stats["total_tokens_sum"] += result.total_tokens
        stats["latency_seconds_sum"] += result.latency_seconds
        stats["cost_sum"] += result.cost

    for stats in by_type.values():
        n = stats["total"] or 1
        stats["accuracy"] = stats["correct"] / n
        stats["db_evidence_rate"] = stats["db_evidence_count"] / n
        stats["avg_sparql_attempts"] = stats["sparql_attempts_sum"] / n
        stats["avg_input_tokens"] = stats["input_tokens_sum"] / n
        stats["avg_output_tokens"] = stats["output_tokens_sum"] / n
        stats["avg_total_tokens"] = stats["total_tokens_sum"] / n
        stats["avg_latency_seconds"] = stats["latency_seconds_sum"] / n
        stats["total_cost"] = stats["cost_sum"]

    return {
        "total": total,
        "successful": len(successful),
        "errors": total - len(successful),
        "correct": correct,
        "incorrect": len(successful) - correct,
        "accuracy": correct / total if total else None,
        "db_evidence_count": db_evidence_count,
        "db_evidence_rate": db_evidence_count / len(successful) if successful else None,
        "avg_sparql_attempts": avg([result.sparql_attempts for result in successful]),
        "avg_input_tokens": avg([result.input_tokens for result in successful]),
        "avg_output_tokens": avg([result.output_tokens for result in successful]),
        "avg_total_tokens": avg([result.total_tokens for result in successful]),
        "avg_latency_seconds": avg([result.latency_seconds for result in successful]),
        "total_cost": sum(result.cost for result in successful),
        "by_type": by_type,
    }


def write_outputs(results: list[BenchmarkResult], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [asdict(result) for result in results]
    jsonl_path = output_dir / "results.jsonl"
    csv_path = output_dir / "results.csv"
    summary_path = output_dir / "summary.json"

    with jsonl_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    if records:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)

    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summarize(results), file, ensure_ascii=False, indent=2)

    return jsonl_path, csv_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run friend's v3 SPARQL generation + self-correction benchmark with token logging."
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--project-root", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = SparqlSelfCorrectConfig.from_project_root(args.project_root)
    runner = SparqlSelfCorrectRunner(config)
    results, output_dir = runner.run(limit=args.limit, offset=args.offset)
    print("\nSummary")
    print(json.dumps(summarize(results), ensure_ascii=False, indent=2))
    print(f"Saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
