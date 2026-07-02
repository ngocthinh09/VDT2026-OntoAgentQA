from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


FRIEND_REPO_COMMIT = "e3493e6c314fcae1903ea59de24ff24a4292fe37"
SYSTEM_PROMPT = "Bạn là một chatbot tiếng Việt hữu ích, trả lời ngắn gọn và rõ ràng."


@dataclass(frozen=True)
class LLMOnlyConfig:
    project_root: Path
    csv_path: Path
    env_path: Path
    output_root: Path
    model: str
    api_key: str
    base_url: str = "https://openrouter.ai/api/v1"
    provider_only: str | None = None
    temperature: float = 0.2
    request_delay_seconds: float = 0.0

    @classmethod
    def from_project_root(cls, project_root: Path | None = None) -> "LLMOnlyConfig":
        root = find_project_root(project_root or Path.cwd())
        env_path = root / ".env"
        load_dotenv(env_path)

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        model = os.getenv("OPENROUTER_MODEL", "")
        if not api_key:
            raise RuntimeError("Missing OPENROUTER_API_KEY in .env")
        if not model:
            raise RuntimeError("Missing OPENROUTER_MODEL in .env")

        return cls(
            project_root=root,
            csv_path=root / "data" / "ontologyqa_test_questions_v1.csv",
            env_path=env_path,
            output_root=root / "experiments" / "results" / "llm_only",
            model=model,
            api_key=api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            provider_only=os.getenv("OPENROUTER_PROVIDER_ONLY") or None,
            temperature=float(os.getenv("CHAT_TEMPERATURE", "0.2")),
            request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "0")),
        )


@dataclass(frozen=True)
class QuestionCase:
    question_id: str
    question: str
    question_type: str
    correct_answer: int
    options: list[str]


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
    valid_answer_count: int
    status: str
    error_type: str | None
    error_message: str | None
    raw_response: str
    model: str
    provider_only: str | None
    temperature: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost: float | None
    latency_seconds: float


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "data" / "ontologyqa_test_questions_v1.csv").exists() and (candidate / ".env").exists():
            return candidate
    raise FileNotFoundError("Cannot find project root containing data/ontologyqa_test_questions_v1.csv and .env")


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_answer(value: object, row_number: int) -> int:
    if value is None or str(value).strip() == "":
        raise ValueError(f"Row {row_number}: answer is empty")
    try:
        answer = int(float(str(value).strip()))
    except ValueError as exc:
        raise ValueError(f"Row {row_number}: answer is not numeric: {value!r}") from exc
    if answer < 1 or answer > 5:
        raise ValueError(f"Row {row_number}: answer must be in 1-5, got {answer}")
    return answer


def load_questions(csv_path: Path) -> list[QuestionCase]:
    cases: list[QuestionCase] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row_number, row in enumerate(reader, start=2):
            question_id = normalize_cell(row.get("number"))
            question = normalize_cell(row.get("vi_question"))
            question_type = normalize_cell(row.get("question_type"))
            options = [normalize_cell(row.get(f"option_{idx}")) for idx in range(1, 6)]
            options = [option for option in options if option]

            if not question:
                print(f"Skipping row {row_number}: missing question", file=sys.stderr)
                continue
            if not options:
                print(f"Skipping row {row_number}: missing options", file=sys.stderr)
                continue

            try:
                correct_answer = parse_answer(row.get("answer"), row_number)
            except ValueError as exc:
                print(f"Skipping row {row_number}: {exc}", file=sys.stderr)
                continue

            if correct_answer > len(options):
                print(
                    f"Skipping row {row_number}: answer={correct_answer} but only {len(options)} options",
                    file=sys.stderr,
                )
                continue

            cases.append(
                QuestionCase(
                    question_id=question_id,
                    question=question,
                    question_type=question_type,
                    correct_answer=correct_answer,
                    options=options,
                )
            )
    return cases


def build_prompt(case: QuestionCase) -> str:
    """Prompt copied from the friend's v1 benchmark_backend.py."""
    options_text = "\n".join(f"{index}. {option}" for index, option in enumerate(case.options, start=1))
    return (
        "Bạn là hệ thống trả lời trắc nghiệm tiếng Việt.\n"
        "Chỉ trả về JSON hợp lệ, không giải thích, không markdown, không thêm ký tự khác.\n"
        'Schema bắt buộc: {"answer":"1"}.\n'
        f'Giá trị answer hợp lệ là chuỗi từ "1" đến "{len(case.options)}".\n\n'
        f"Câu hỏi: {case.question}\n\n"
        f"Các đáp án:\n{options_text}\n\n"
        "JSON:"
    )


def build_messages(case: QuestionCase) -> list[dict[str, str]]:
    """Message shape copied from the friend's v1 backend/app/main.py."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(case)},
    ]


def extract_answer(raw_response: str, valid_answer_count: int) -> int | None:
    text = raw_response.strip()
    json_text = text

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced_match:
        json_text = fenced_match.group(1)
    elif not text.startswith("{"):
        object_match = re.search(r"\{.*?\}", text, flags=re.DOTALL)
        if object_match:
            json_text = object_match.group(0)

    try:
        data = json.loads(json_text)
        if isinstance(data, dict):
            answer_value = str(data.get("answer", "")).strip()
            if re.fullmatch(r"[1-5]", answer_value):
                value = int(answer_value)
                return value if 1 <= value <= valid_answer_count else None
    except json.JSONDecodeError:
        pass

    candidates = [int(value) for value in re.findall(r"(?<!\d)([1-5])(?!\d)", text)]
    for value in candidates:
        if 1 <= value <= valid_answer_count:
            return value
    return None


def build_extra_body(provider_only: str | None) -> dict[str, Any] | None:
    if not provider_only:
        return None
    providers = [provider.strip() for provider in provider_only.split(",") if provider.strip()]
    return {"provider": {"only": providers}} if providers else None


def usage_int(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if value is not None:
            return int(value)
    return None


class LLMOnlyRunner:
    def __init__(self, config: LLMOnlyConfig):
        self.config = config
        self.client = OpenAI(base_url=config.base_url, api_key=config.api_key)

    def run_case(self, run_id: str, case: QuestionCase) -> BenchmarkResult:
        request_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": build_messages(case),
            "temperature": self.config.temperature,
        }
        extra_body = build_extra_body(self.config.provider_only)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        started = time.perf_counter()
        content = ""
        usage: dict[str, Any] = {}
        error: Exception | None = None
        try:
            completion = self.client.chat.completions.create(**request_kwargs)
            raw_response = completion.model_dump()
            content = completion.choices[0].message.content or ""
            usage = raw_response.get("usage") or {}
        except Exception as exc:
            error = exc
        latency = time.perf_counter() - started

        predicted = extract_answer(content, len(case.options)) if error is None else None
        input_tokens = usage_int(usage, "prompt_tokens", "input_tokens")
        output_tokens = usage_int(usage, "completion_tokens", "output_tokens")
        total_tokens = usage_int(usage, "total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

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
            valid_answer_count=len(case.options),
            status="error" if error else "success",
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
            raw_response=content,
            model=self.config.model,
            provider_only=self.config.provider_only,
            temperature=self.config.temperature,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=usage.get("cost"),
            latency_seconds=latency,
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

        run_id = f"llm-only-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        output_dir = self.config.output_root / run_id
        results: list[BenchmarkResult] = []

        print(f"Run ID: {run_id}")
        print(f"Source commit: {FRIEND_REPO_COMMIT}")
        print(f"Cases: {len(cases)}")
        print(f"Model: {self.config.model}")
        print(f"Provider only: {self.config.provider_only}")
        print(f"Output dir: {output_dir}")

        for index, case in enumerate(cases, start=1):
            result = self.run_case(run_id, case)
            results.append(result)
            print(
                f"[{index}/{len(cases)}] id={case.question_id} status={result.status} "
                f"pred={result.predicted_answer} correct={case.correct_answer} ok={result.is_correct} "
                f"in={result.input_tokens} out={result.output_tokens} "
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

    def avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    by_type: dict[str, dict[str, Any]] = {}
    for result in successful:
        stats = by_type.setdefault(
            result.question_type or "unknown",
            {
                "total": 0,
                "correct": 0,
                "input_tokens_sum": 0,
                "output_tokens_sum": 0,
                "total_tokens_sum": 0,
                "latency_seconds_sum": 0.0,
                "cost_sum": 0.0,
            },
        )
        stats["total"] += 1
        stats["correct"] += int(result.is_correct)
        stats["input_tokens_sum"] += result.input_tokens or 0
        stats["output_tokens_sum"] += result.output_tokens or 0
        stats["total_tokens_sum"] += result.total_tokens or 0
        stats["latency_seconds_sum"] += result.latency_seconds
        stats["cost_sum"] += result.cost or 0.0

    for stats in by_type.values():
        n = stats["total"] or 1
        stats["accuracy"] = stats["correct"] / n
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
        "avg_input_tokens": avg([result.input_tokens or 0 for result in successful]),
        "avg_output_tokens": avg([result.output_tokens or 0 for result in successful]),
        "avg_total_tokens": avg([result.total_tokens or 0 for result in successful]),
        "avg_latency_seconds": avg([result.latency_seconds for result in successful]),
        "total_cost": sum(result.cost or 0.0 for result in successful),
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
    parser = argparse.ArgumentParser(description="Run friend's v1 LLM-only benchmark with token logging.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--project-root", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = LLMOnlyConfig.from_project_root(args.project_root)
    runner = LLMOnlyRunner(config)
    results, output_dir = runner.run(limit=args.limit, offset=args.offset)
    print("\nSummary")
    print(json.dumps(summarize(results), ensure_ascii=False, indent=2))
    print(f"Saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
