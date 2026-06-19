from __future__ import annotations

import ast
import json
import operator
import os
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agents.kg_tools import KG_TOOLS
from agents.search_tools import SEARCH_TOOLS


DEFAULT_MAX_ITERATIONS = 15

ONTOLOGY_QA_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompt" / "controller.prompt").read_text(encoding="utf-8")
REPORTER_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompt" / "reporter.prompt").read_text(encoding="utf-8")


class OntologyQAInput(TypedDict):
    question: str
    options: list[dict[str, Any]]


class OntologyQAOutput(TypedDict):
    selected_option_id: int | str | None
    answer: str
    result: Any


class OntologyQAState(TypedDict, total=False):
    question: str
    options: list[dict[str, Any]]
    messages: Annotated[list[AnyMessage], add_messages]
    steps: Annotated[list[dict[str, Any]], operator.add]
    actions: Annotated[list[dict[str, Any]], operator.add]
    generated_sparqls: Annotated[list[str], operator.add]
    executions: Annotated[list[dict[str, Any]], operator.add]
    last_execution_result: Any
    result: Any
    final_sparql: str | None
    finalization_error: str | None
    selected_option_id: int | str | None
    answer: str | None
    iteration_count: int


def build_openrouter_chat_model(
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> Any:
    """Create a LangChain ChatOpenAI model configured for OpenRouter."""
    load_dotenv()

    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing dependency 'langchain-openai'. Install requirements.txt before "
            "building the ontology QA agent."
        ) from exc

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is required to build the ontology QA agent.")

    selected_model = model or os.environ.get("OPENROUTER_MODEL")
    if not selected_model:
        raise ValueError("OPENROUTER_MODEL is required to build the ontology QA agent.")

    extra_body: dict[str, Any] = {}
    provider_only = os.environ.get("OPENROUTER_PROVIDER_ONLY")
    if provider_only:
        extra_body["provider"] = {
            "only": [item.strip() for item in provider_only.split(",") if item.strip()]
        }

    kwargs: dict[str, Any] = {
        "model": selected_model,
        "api_key": api_key,
        "base_url": os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if extra_body:
        kwargs["extra_body"] = extra_body

    return ChatOpenAI(**kwargs)


def _initial_messages(question: str) -> list[AnyMessage]:
    return [
        SystemMessage(content=ONTOLOGY_QA_SYSTEM_PROMPT),
        HumanMessage(content=question),
    ]


def _parse_tool_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content

    text = content.strip()
    if not text:
        return ""

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return text


def _is_successful_execution(result: Any) -> bool:
    if isinstance(result, bool):
        return True
    if isinstance(result, list):
        return any(_has_bound_value(row) for row in result)
    if isinstance(result, dict) and result.get("ok") is False:
        return False
    return bool(result)


def _has_bound_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return any(_has_bound_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_bound_value(item) for item in value.values())
    return bool(value)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    clean = text.strip()
    if not clean:
        return None

    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    return value if isinstance(value, dict) else None


def _find_last_ai_with_tool_calls(messages: list[AnyMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.tool_calls:
            return message
    return None


def _tool_call_by_id(ai_message: AIMessage | None) -> dict[str, dict[str, Any]]:
    if ai_message is None:
        return {}
    return {call.get("id", ""): call for call in ai_message.tool_calls}


def _canonical_args(args: Any) -> str:
    if isinstance(args, Mapping):
        return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return str(args)


def _tool_call_key(tool_name: str, args: Any) -> str:
    return f"{tool_name}:{_canonical_args(args)}"


def _executed_tool_call_keys(steps: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for step in steps:
        tool_name = str(step.get("tool") or "")
        if tool_name:
            keys.add(_tool_call_key(tool_name, step.get("args") or {}))
    return keys


def _duplicate_tool_calls(state: OntologyQAState) -> list[dict[str, Any]]:
    messages = state.get("messages", [])
    if not messages or not isinstance(messages[-1], AIMessage):
        return []

    seen = _executed_tool_call_keys(state.get("steps", []))
    duplicates: list[dict[str, Any]] = []
    for call in messages[-1].tool_calls:
        tool_name = str(call.get("name") or "")
        args = call.get("args") or {}
        if _tool_call_key(tool_name, args) in seen:
            duplicates.append({"tool": tool_name, "args": args})
    return duplicates


def _initialize_node(state: OntologyQAState) -> dict[str, Any]:
    question = state.get("question", "").strip()
    if not question:
        raise ValueError("question is required")
    return {
        "messages": _initial_messages(question),
        "iteration_count": 0,
        "steps": [],
        "actions": [],
        "generated_sparqls": [],
        "executions": [],
    }


def _make_agent_node(model: Any) -> Any:
    model_with_tools = model.bind_tools(SEARCH_TOOLS + KG_TOOLS)

    def agent_node(state: OntologyQAState) -> dict[str, Any]:
        iteration_count = int(state.get("iteration_count", 0)) + 1
        response = model_with_tools.invoke(state["messages"])
        return {
            "messages": [response],
            "iteration_count": iteration_count,
        }

    return agent_node


def _post_tool_node(state: OntologyQAState) -> dict[str, Any]:
    messages = state.get("messages", [])
    calls = _tool_call_by_id(_find_last_ai_with_tool_calls(messages))
    current_tool_messages: list[ToolMessage] = []
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break
        current_tool_messages.append(message)
    current_tool_messages.reverse()

    steps: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    generated_sparqls: list[str] = []
    last_execution_result: Any = None
    has_execution = False

    for message in current_tool_messages:
        call = calls.get(message.tool_call_id, {})
        tool_name = call.get("name") or message.name or ""
        args = call.get("args") or {}
        result = _parse_tool_content(message.content)

        steps.append(
            {
                "tool": tool_name,
                "args": args,
                "result": result,
            }
        )

        if tool_name == "execute_sparql":
            query = str(args.get("query", ""))
            generated_sparqls.append(query)
            executions.append(
                {
                    "query": query,
                    "result": result,
                    "ok": _is_successful_execution(result),
                }
            )
            last_execution_result = result
            has_execution = True

    update: dict[str, Any] = {
        "steps": steps,
        "actions": steps,
        "generated_sparqls": generated_sparqls,
        "executions": executions,
    }
    if has_execution:
        update["last_execution_result"] = last_execution_result
        if _is_successful_execution(last_execution_result):
            update["final_sparql"] = generated_sparqls[-1]
            update["result"] = last_execution_result
    return update


def _has_tool_calls(state: OntologyQAState) -> bool:
    messages = state.get("messages", [])
    if not messages:
        return False
    last_message = messages[-1]
    return isinstance(last_message, AIMessage) and bool(last_message.tool_calls)


def _has_successful_execution(state: OntologyQAState) -> bool:
    return any(execution.get("ok") for execution in state.get("executions", []))


def _route_after_agent(
    state: OntologyQAState,
    max_iterations: int,
) -> Literal["tools", "retry", "finalize"]:
    if int(state.get("iteration_count", 0)) >= max_iterations:
        return "finalize"
    if _has_tool_calls(state):
        if _duplicate_tool_calls(state):
            return "retry"
        return "tools"
    if _has_successful_execution(state):
        return "finalize"
    return "retry"


def _retry_node(state: OntologyQAState) -> dict[str, Any]:
    duplicates = _duplicate_tool_calls(state)
    if duplicates:
        duplicate_text = json.dumps(duplicates, ensure_ascii=False, default=str)
        content = (
            "You just requested a duplicate tool call that has already been "
            f"executed: {duplicate_text}. Do not repeat the same action with "
            "the same arguments. Choose a different grounding, inspect another "
            "edge/example, or execute a revised SPARQL query."
        )
    else:
        content = (
            "You cannot stop yet because no successful execute_sparql "
            "result exists. Call exactly one appropriate tool next. If "
            "you have a candidate query, call execute_sparql."
        )

    return {
        "messages": [
            HumanMessage(content=content)
        ]
    }


def _finalize_node(state: OntologyQAState) -> dict[str, Any]:
    messages = state.get("messages", [])
    final_payload: dict[str, Any] | None = None
    if messages and isinstance(messages[-1], AIMessage):
        final_payload = _extract_json_object(str(messages[-1].content))

    final_sparql = state.get("final_sparql")
    result = state.get("result")
    answer = str(messages[-1].content) if messages and isinstance(messages[-1], AIMessage) else ""
    if final_payload:
        answer = str(final_payload.get("answer") or "")

    if _has_successful_execution(state) and final_sparql:
        return {
            "final_sparql": final_sparql,
            "answer": answer,
            "last_execution_result": result,
            "result": result,
            "finalization_error": None,
        }

    return {
        "final_sparql": None,
        "answer": answer or "No successful SPARQL execution was produced.",
        "result": result,
        "finalization_error": "No successful SPARQL execution was produced.",
    }


def _normalize_selected_option_id(
    selected_option_id: Any,
    options: list[dict[str, Any]],
) -> int | str | None:
    if selected_option_id is None:
        return None

    exact_matches = [option.get("id") for option in options if option.get("id") == selected_option_id]
    if len(exact_matches) == 1:
        return exact_matches[0]

    string_matches = [
        option.get("id")
        for option in options
        if str(option.get("id")) == str(selected_option_id)
    ]
    return string_matches[0] if len(string_matches) == 1 else None


def _make_reporter_node(model: Any) -> Any:
    def reporter_node(state: OntologyQAState) -> dict[str, Any]:
        options = state.get("options", [])
        reporter_payload = {
            "question": state.get("question", ""),
            "options": options,
            "controller_answer": state.get("answer"),
            "final_sparql": state.get("final_sparql"),
            "query_result": state.get("result"),
            "executions": state.get("executions", []),
            "finalization_error": state.get("finalization_error"),
        }
        response = model.invoke(
            [
                SystemMessage(content=REPORTER_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(reporter_payload, ensure_ascii=False, default=str)
                ),
            ]
        )
        report = _extract_json_object(str(response.content)) or {}
        selected_option_id = _normalize_selected_option_id(
            report.get("selected_option_id", report.get("selection_id")),
            options,
        )
        if state.get("finalization_error"):
            selected_option_id = None

        answer = str(state.get("answer") or "")
        compatibility_answer_text = str(
            report.get("answer") or report.get("answer_text") or answer
        ).strip()

        return {
            "selected_option_id": selected_option_id,
            "answer": answer,
            "result": state.get("result"),
            "final_sparql": state.get("final_sparql"),
            # Compatibility aliases for callers of the previous reporter helper.
            "selection_id": selected_option_id,
            "answer_text": compatibility_answer_text,
        }

    return reporter_node


def _make_finalize_node(model: Any) -> Any:
    reporter_node = _make_reporter_node(model)

    def finalize_node(state: OntologyQAState) -> dict[str, Any]:
        evidence = _finalize_node(state)
        report = reporter_node({**state, **evidence})
        return {
            **evidence,
            "selected_option_id": report["selected_option_id"],
            "answer": report["answer"],
            "result": evidence.get("result"),
        }

    return finalize_node


def build_ontology_qa_agent(
    *,
    model: Any | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> Runnable:
    """Build the LangGraph ontology QA agent."""
    chat_model = model or build_openrouter_chat_model(
        temperature=temperature,
        max_tokens=max_tokens,
    )

    graph = StateGraph(
        OntologyQAState,
        input_schema=OntologyQAInput,
        output_schema=OntologyQAOutput,
    )
    graph.add_node("initialize", _initialize_node)
    graph.add_node("agent", _make_agent_node(chat_model))
    graph.add_node("tools", ToolNode(SEARCH_TOOLS + KG_TOOLS))
    graph.add_node("post_tool", _post_tool_node)
    graph.add_node("retry", _retry_node)
    graph.add_node("finalize", _make_finalize_node(chat_model))

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "agent")
    graph.add_conditional_edges(
        "agent",
        lambda state: _route_after_agent(state, max_iterations),
        {
            "tools": "tools",
            "retry": "retry",
            "finalize": "finalize",
        },
    )
    graph.add_edge("tools", "post_tool")
    graph.add_edge("post_tool", "agent")
    graph.add_edge("retry", "agent")
    graph.add_edge("finalize", END)

    return graph.compile()


__all__ = [
    "DEFAULT_MAX_ITERATIONS",
    "ONTOLOGY_QA_SYSTEM_PROMPT",
    "REPORTER_SYSTEM_PROMPT",
    "OntologyQAInput",
    "OntologyQAOutput",
    "OntologyQAState",
    "build_ontology_qa_agent",
    "build_openrouter_chat_model",
]
