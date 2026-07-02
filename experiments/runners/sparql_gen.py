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

import requests
from dotenv import load_dotenv
from openai import OpenAI


FRIEND_REPO_COMMIT = "0e8bcee"

OPTIONS_BLOCK_PATTERN = re.compile(
    r"(?is)(?:c[aá]c\s+)?(?:(?:đ|d)[aá]p\s*[aá]n|answer\s+options?|options?)\s*:?\s*\n?.*$"
)
NUMBERED_OPTION_PATTERN = re.compile(r"(?m)^\s*(?:[1-5]|[A-Ea-e])[\).:-]\s+.+$")
READ_ONLY_SPARQL_PATTERN = re.compile(
    r"\b(INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|MOVE|COPY|ADD|SERVICE)\b",
    re.IGNORECASE,
)
PREFIX_DECLARATION_PATTERN = re.compile(r"(?im)^\s*PREFIX\s+([A-Za-z][\w-]*):")
PREFIX_USAGE_PATTERN = re.compile(r"(?<![\w:/#])([A-Za-z][\w-]*):[A-Za-z_][\w.-]*")

COMMON_PREFIXES = {
    "dbo": "http://dbpedia.org/ontology/",
    "dbr": "http://dbpedia.org/resource/",
    "dbp": "http://dbpedia.org/property/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "owl": "http://www.w3.org/2002/07/owl#",
}

ONTOLOGY_HINTS = """
Local GraphDB schema hints from Ontology/ontology--DEV_type=parsed_sorted.nt:
- The graph uses DBpedia ontology IRIs. Main namespace: http://dbpedia.org/ontology/ as dbo:.
- Resource namespace is usually http://dbpedia.org/resource/ as dbr:.
- Labels are stored with rdfs:label, often with @en language tags.
- Classes are declared as owl:Class. Examples:
  dbo:Academic, dbo:AcademicConference, dbo:AcademicJournal, dbo:AcademicSubject,
  dbo:Activity, dbo:Actor, dbo:AdministrativeRegion, dbo:Agent, dbo:Aircraft,
  dbo:Airline, dbo:Airport, dbo:Album, dbo:Ambassador, dbo:Animal, dbo:Architect,
  dbo:ArchitecturalStructure, dbo:Artist, dbo:Artwork, dbo:Astronaut, dbo:Athlete,
  dbo:Automobile, dbo:Award, dbo:Band, dbo:Bank, dbo:BaseballPlayer,
  dbo:BasketballPlayer, dbo:BasketballTeam, dbo:Bay, dbo:Beach.
- Object properties are declared as owl:ObjectProperty and connect resources to resources. Examples:
  dbo:academicAdvisor, dbo:academicDiscipline, dbo:academyAward, dbo:achievement,
  dbo:activity, dbo:adjacentSettlement, dbo:administrativeCenter,
  dbo:administrator, dbo:affiliation, dbo:agency, dbo:airline, dbo:album,
  dbo:almaMater, dbo:architect, dbo:architecturalStyle, dbo:artist,
  dbo:author, dbo:award, dbo:bandMember, dbo:basedOn, dbo:basinCountry.
- Some numeric/literal datatype properties are class-scoped IRIs, not normal dbo:localName CURIEs.
  Use full IRIs for these, for example:
  <http://dbpedia.org/ontology/Person/height>, <http://dbpedia.org/ontology/Person/weight>,
  <http://dbpedia.org/ontology/Building/floorArea>,
  <http://dbpedia.org/ontology/Automobile/fuelCapacity>,
  <http://dbpedia.org/ontology/Automobile/wheelbase>,
  <http://dbpedia.org/ontology/Engine/topSpeed>,
  <http://dbpedia.org/ontology/Engine/powerOutput>,
  <http://dbpedia.org/ontology/PopulatedPlace/areaTotal>,
  <http://dbpedia.org/ontology/PopulatedPlace/populationDensity>,
  <http://dbpedia.org/ontology/Lake/volume>.
- Datatype units use http://dbpedia.org/datatype/, for example metre, kilometre, kilogram, kelvin,
  squareKilometre, inhabitantsPerSquareKilometre.
- If an exact property is uncertain, first prefer broad predicate discovery queries using rdfs:label filters
  and return candidate ?p ?pLabel ?value. Do not invent properties outside dbo:, dbp:, rdf:, rdfs:, foaf:.
""".strip()


@dataclass(frozen=True)
class SparqlGenConfig:
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
    graphdb_timeout_seconds: int = 150
    graphdb_max_rows: int = 20

    @classmethod
    def from_project_root(cls, project_root: Path | None = None) -> "SparqlGenConfig":
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

        timeout_value = os.getenv("GRAPHDB_TIMEOUT") or os.getenv("GRAPHDB_QUERY_TIMEOUT_SECONDS") or "150"

        return cls(
            project_root=root,
            csv_path=root / "data" / "ontologyqa_test_questions_v1.csv",
            env_path=env_path,
            output_root=root / "experiments" / "results" / "sparql_gen",
            model=model,
            api_key=api_key,
            graphdb_endpoint=graphdb_endpoint.rstrip("/"),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            provider_only=os.getenv("OPENROUTER_PROVIDER_ONLY") or None,
            temperature=float(os.getenv("CHAT_TEMPERATURE", "0.2")),
            request_delay_seconds=float(os.getenv("REQUEST_DELAY_SECONDS", "0")),
            graphdb_timeout_seconds=int(float(timeout_value)),
            graphdb_max_rows=int(os.getenv("GRAPHDB_MAX_ROWS", "20")),
        )


@dataclass(frozen=True)
class QuestionCase:
    question_id: str
    question: str
    question_type: str
    correct_answer: int
    options: list[str]


@dataclass(frozen=True)
class LLMCallRecord:
    step: str
    content: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost: float | None
    latency_seconds: float


@dataclass(frozen=True)
class PipelineOutput:
    final_response: str
    routing_decision: dict[str, Any]
    sparql: str
    graphdb_result_summary: dict[str, Any] | None
    graphdb_error: str | None
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
    status: str
    error_type: str | None
    error_message: str | None
    raw_response: str
    routing_decision: str
    sparql: str
    graphdb_result_summary: str
    graphdb_error: str | None
    llm_calls: str
    model: str
    provider_only: str | None
    temperature: float
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    latency_seconds: float


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "data" / "ontologyqa_test_questions_v1.csv").exists() and (candidate / ".env").exists():
            return candidate
    raise FileNotFoundError("Cannot find project root containing data/ontologyqa_test_questions_v1.csv and .env")


def build_repository_url_from_env() -> str:
    graphdb_url = os.getenv("GRAPHDB_URL", "").rstrip("/")
    repository = os.getenv("GRAPHDB_REPOSITORY", "").strip()
    if graphdb_url and repository:
        return f"{graphdb_url}/repositories/{repository}"
    return ""


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


def build_benchmark_prompt(case: QuestionCase) -> str:
    """Prompt copied from friend's v2 bench/benchmark_backend.py."""
    options_text = "\n".join(f"{index}. {option}" for index, option in enumerate(case.options, start=1))
    return (
        "Bạn là hệ thống trả lời trắc nghiệm tiếng Việt.\n"
        "Chỉ trả về JSON hợp lệ, không giải thích, không markdown, không thêm ký tự khác.\n"
        'Schema bắt buộc: {"answer":"1"}.\n'
        f'Giá trị answer hợp lệ là chuỗi từ "1" đến "{len(case.options)}".\n\n'
        f"Câu hỏi: {case.question}\n\n"
        f"Các đáp án:\n{options_text}\n\n"
        'If SPARQL/GraphDB evidence is available, choose the option supported by that evidence and return {"answer":"1","evidence":["short evidence"]}; only guess the most likely option when no usable SPARQL evidence exists.\n'
        "JSON:"
    )


def system_message(content: str) -> dict[str, str]:
    return {"role": "system", "content": content}


def user_message(content: str) -> dict[str, str]:
    return {"role": "user", "content": content}


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    object_match = fenced_match or re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if not object_match:
        return {}

    json_text = object_match.group(1) if fenced_match else object_match.group(0)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def strip_answer_options(text: str) -> str:
    stripped = OPTIONS_BLOCK_PATTERN.sub("", text).strip()
    stripped = NUMBERED_OPTION_PATTERN.sub("", stripped).strip()
    return stripped or text


def is_multiple_choice_prompt(message: str) -> bool:
    return bool(NUMBERED_OPTION_PATTERN.search(message))


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


def add_missing_common_prefixes(query: str) -> str:
    declared_prefixes = set(PREFIX_DECLARATION_PATTERN.findall(query))
    used_prefixes = set(PREFIX_USAGE_PATTERN.findall(query))
    missing_prefixes = [
        prefix for prefix in COMMON_PREFIXES
        if prefix in used_prefixes and prefix not in declared_prefixes
    ]
    if not missing_prefixes:
        return query

    declarations = "\n".join(
        f"PREFIX {prefix}: <{COMMON_PREFIXES[prefix]}>" for prefix in missing_prefixes
    )
    return f"{declarations}\n{query}"


def is_read_only_sparql(query: str) -> bool:
    if not query or READ_ONLY_SPARQL_PATTERN.search(query):
        return False
    without_prefixes = re.sub(r"(?im)^\s*PREFIX\s+[^\n]+\n?", "", query).strip()
    return without_prefixes.upper().startswith(("SELECT", "ASK"))


def summarize_graphdb_result(result: dict[str, Any]) -> dict[str, Any]:
    if "boolean" in result:
        return {"type": "ask", "value": bool(result["boolean"])}

    bindings = result.get("results", {}).get("bindings", [])
    sample = bindings[:2] if isinstance(bindings, list) else []
    return {
        "type": "select",
        "vars": result.get("head", {}).get("vars", []),
        "row_count": len(bindings) if isinstance(bindings, list) else 0,
        "sample": sample,
    }


def has_graphdb_result(result: dict[str, Any]) -> bool:
    if "boolean" in result:
        return True
    bindings = result.get("results", {}).get("bindings", [])
    return isinstance(bindings, list) and len(bindings) > 0


def format_graphdb_result(result: dict[str, Any], max_rows: int) -> str:
    if "boolean" in result:
        return json.dumps({"ask": bool(result["boolean"])}, ensure_ascii=False)

    variables = result.get("head", {}).get("vars", [])
    bindings = result.get("results", {}).get("bindings", [])
    rows: list[dict[str, str]] = []
    for binding in bindings[:max_rows]:
        row: dict[str, str] = {}
        for variable in variables:
            value = binding.get(variable, {})
            row[variable] = str(value.get("value", ""))
        rows.append(row)
    return json.dumps({"rows": rows, "row_count": len(bindings)}, ensure_ascii=False, indent=2)


def extract_answer(raw_response: str, valid_answer_count: int) -> int | None:
    text = raw_response.strip()
    data = extract_json_object(raw_response)
    if data:
        answer_value = str(data.get("answer", "")).strip()
        if re.fullmatch(r"[1-5]", answer_value):
            value = int(answer_value)
            return value if 1 <= value <= valid_answer_count else None

    candidates = [int(value) for value in re.findall(r"(?<!\d)([1-5])(?!\d)", text)]
    for value in candidates:
        if 1 <= value <= valid_answer_count:
            return value
    return None


def has_db_evidence(raw_response: str) -> bool:
    data = extract_json_object(raw_response)
    evidence = data.get("evidence") if data else None
    if not isinstance(evidence, list):
        return False

    evidence_text = "\n".join(str(item) for item in evidence).lower()
    fallback_markers = (
        "no usable sparql evidence",
        "best-effort guess",
        "fallback",
        "no_graphdb_result",
        "graphdb_error",
        "graphdb_timeout",
    )
    if any(marker in evidence_text for marker in fallback_markers):
        return False
    return bool(evidence_text.strip())


class SparqlGenRunner:
    def __init__(self, config: SparqlGenConfig):
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

    def direct_answer_messages(self, message: str) -> list[dict[str, str]]:
        return [
            system_message(
                "You are a helpful Vietnamese chatbot. Answer clearly and concisely. "
                "For multiple-choice prompts, return only valid JSON with this schema: "
                "{\"answer\":\"1\",\"evidence\":[\"short evidence or fallback reason\"]}. "
                "The answer value must be the selected option ID as a string."
            ),
            user_message(message),
        ]

    def final_answer_messages(
        self,
        message: str,
        decision: dict[str, Any],
        sparql: str,
        graphdb_result: dict[str, Any] | None,
        graphdb_error: str | None = None,
    ) -> list[dict[str, str]]:
        if graphdb_result:
            result_text = format_graphdb_result(graphdb_result, self.config.graphdb_max_rows)
        elif graphdb_error:
            result_text = graphdb_error
        else:
            result_text = "NO_GRAPHDB_RESULT"
        return [
            system_message(
                "You are the central answering agent for a Vietnamese chatbot. "
                "For multiple-choice prompts, always return only valid JSON with this schema: "
                "{\"answer\":\"1\",\"evidence\":[\"short evidence text\"]}. "
                "The answer value must be the selected option ID as a string. "
                "Evidence must be a JSON array of short strings. "
                "If GraphDB rows are provided, compare those facts with the original choices and choose only the option supported by GraphDB evidence. "
                "In that case, every evidence item must cite a concrete value, entity, relationship, date, count, or literal from the GraphDB result. "
                "If GraphDB returned no result, no SPARQL was executed, or a timeout/error status is provided, then and only then choose the option that seems most likely from general knowledge. "
                "For fallback answers, set evidence to a single item explaining that there was no usable SPARQL evidence and that the choice is a best-effort guess. "
                "For non-multiple-choice prompts, answer clearly and include GraphDB evidence when available."
            ),
            user_message(
                f"Original prompt including any answer choices:\n{message}\n\n"
                f"Central routing decision:\n{json.dumps(decision, ensure_ascii=False)}\n\n"
                f"Executed SPARQL:\n{sparql or 'NO_SPARQL_EXECUTED'}\n\n"
                f"GraphDB result:\n{result_text}\n\n"
                "Return the final answer to the user."
            ),
        ]

    def normalize_answer_evidence_response(
        self,
        message: str,
        raw_text: str,
        graphdb_result: dict[str, Any] | None = None,
        graphdb_error: str | None = None,
    ) -> str:
        if not is_multiple_choice_prompt(message):
            return raw_text

        data = extract_json_object(raw_text)
        answer = str(data.get("answer", "")).strip() if data else ""
        if not re.fullmatch(r"[1-5]", answer):
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

    def query_graphdb(self, sparql: str) -> dict[str, Any]:
        response = requests.post(
            self.config.graphdb_endpoint,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
            timeout=(5, self.config.graphdb_timeout_seconds),
        )
        response.raise_for_status()
        return response.json()

    def run_pipeline(self, user_prompt: str) -> PipelineOutput:
        started = time.perf_counter()
        calls: list[LLMCallRecord] = []
        decision = self.plan_graphdb_usage(user_prompt, calls)
        sparql = ""
        graphdb_result: dict[str, Any] | None = None
        graphdb_error: str | None = None
        final_raw = ""

        if not decision["use_graphdb"]:
            call = self.complete("central_final_direct", self.direct_answer_messages(user_prompt))
            calls.append(call)
            final_raw = self.normalize_answer_evidence_response(user_prompt, call.content)
            return PipelineOutput(final_raw, decision, sparql, None, graphdb_error, calls, time.perf_counter() - started)

        try:
            sparql = self.generate_sparql(user_prompt, decision["query_description"], calls)
            graphdb_result = self.query_graphdb(sparql) if sparql else None
        except requests.Timeout as exc:
            graphdb_error = "GRAPHDB_TIMEOUT: GraphDB query exceeded the configured timeout."
            graphdb_result = None
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            graphdb_error = f"GRAPHDB_ERROR: {type(exc).__name__}: {exc}"
            graphdb_result = None

        has_result = bool(graphdb_result and has_graphdb_result(graphdb_result))
        if has_result:
            final_messages = self.final_answer_messages(user_prompt, decision, sparql, graphdb_result)
            call = self.complete("central_final_graphdb_answer", final_messages)
            calls.append(call)
            final_raw = self.normalize_answer_evidence_response(user_prompt, call.content, graphdb_result)
        else:
            final_messages = self.final_answer_messages(user_prompt, decision, sparql, None, graphdb_error)
            call = self.complete("central_final_fallback_answer", final_messages)
            calls.append(call)
            final_raw = self.normalize_answer_evidence_response(user_prompt, call.content, None, graphdb_error)

        return PipelineOutput(
            final_response=final_raw,
            routing_decision=decision,
            sparql=sparql,
            graphdb_result_summary=summarize_graphdb_result(graphdb_result) if graphdb_result else None,
            graphdb_error=graphdb_error,
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
            status="error" if error else "success",
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
            raw_response=raw_response,
            routing_decision=json.dumps(pipeline.routing_decision if pipeline else {}, ensure_ascii=False),
            sparql=pipeline.sparql if pipeline else "",
            graphdb_result_summary=json.dumps(pipeline.graphdb_result_summary if pipeline else None, ensure_ascii=False),
            graphdb_error=pipeline.graphdb_error if pipeline else None,
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

        run_id = f"sparql-gen-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        output_dir = self.config.output_root / run_id
        results: list[BenchmarkResult] = []

        print(f"Run ID: {run_id}")
        print(f"Source commit: {FRIEND_REPO_COMMIT}")
        print(f"Cases: {len(cases)}")
        print(f"Model: {self.config.model}")
        print(f"Provider only: {self.config.provider_only}")
        print(f"GraphDB: {self.config.graphdb_endpoint}")
        print(f"Output dir: {output_dir}")

        for index, case in enumerate(cases, start=1):
            result = self.run_case(run_id, case)
            results.append(result)
            print(
                f"[{index}/{len(cases)}] id={case.question_id} status={result.status} "
                f"pred={result.predicted_answer} correct={case.correct_answer} ok={result.is_correct} "
                f"db_evidence={result.has_db_evidence} tokens={result.total_tokens} "
                f"(in={result.input_tokens}, out={result.output_tokens}) "
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
        stats["input_tokens_sum"] += result.input_tokens
        stats["output_tokens_sum"] += result.output_tokens
        stats["total_tokens_sum"] += result.total_tokens
        stats["latency_seconds_sum"] += result.latency_seconds
        stats["cost_sum"] += result.cost

    for stats in by_type.values():
        n = stats["total"] or 1
        stats["accuracy"] = stats["correct"] / n
        stats["db_evidence_rate"] = stats["db_evidence_count"] / n
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
    parser = argparse.ArgumentParser(description="Run friend's v2 SPARQL generation benchmark with token logging.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--project-root", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = SparqlGenConfig.from_project_root(args.project_root)
    runner = SparqlGenRunner(config)
    results, output_dir = runner.run(limit=args.limit, offset=args.offset)
    print("\nSummary")
    print(json.dumps(summarize(results), ensure_ascii=False, indent=2))
    print(f"Saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
