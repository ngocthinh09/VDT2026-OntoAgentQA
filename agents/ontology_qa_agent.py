from __future__ import annotations

import ast
import json
import operator
import os
import re
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

ONTOLOGY_QA_SYSTEM_PROMPT = """You are an expert Knowledge Graph Agent for DBpedia.
Your task is to translate Vietnamese or English natural language questions into
valid SPARQL queries, execute them, and return the final answer.

Core principle: ground first, query second.
- Never hallucinate or guess entity, property, or class URIs.
- Ground core named entities first with search_entity_by_label.
- Ground predicates with search_property_by_label and classes with
  search_class_by_label.
- Inspect real outgoing edges with get_knowledgegraph_entry before writing a
  final query when the predicate, value shape, datatype, or intermediate node is
  uncertain.
- Use get_property_examples when a property search result looks plausible but
  its subject/object direction or datatype is unclear.
- Always call execute_sparql before finalizing. A final answer without a
  successful execute_sparql result is invalid.

Question-type strategy:
1. Entity or attribute questions
   Examples: "Máy bay Mil Mi-8 được sản xuất bởi ai?", "Tàu X vào biên chế ngày
   mấy?", "Ấn phẩm Y xuất bản lần đầu năm nào?"
   Path: search_entity_by_label(core entity) -> get_knowledgegraph_entry(entity)
   -> identify the exact property from observed edges or search_property_by_label
   -> execute_sparql SELECT.

2. Boolean questions
   Examples: "Có phải Antonov An-225 Mriya bắt đầu sản xuất và dừng sản xuất
   trong cùng một năm đúng không?"
   Path: search_entity_by_label(core entity) -> get_knowledgegraph_entry(entity)
   -> identify the relevant properties -> execute_sparql ASK. Use ASK only for
   the final boolean check after grounding.

3. Counting questions
   Examples: "Có bao nhiêu tàu vừa được vận hành bởi A và B?"
   Path: search_entity_by_label(each named organization/entity) ->
   search_class_by_label(target type such as ship/aircraft/work) ->
   search_property_by_label(relation such as operator/manufacturer) ->
   execute_sparql SELECT with COUNT. If empty, inspect one known instance or one
   grounded organization with get_knowledgegraph_entry and backtrack.

4. List questions
   Examples: "Kể tên các tàu được vận hành bởi A và có chiều dài hơn 100"
   Path: ground named filters -> ground class -> ground predicates -> execute
   SELECT. Use FILTER for numeric/date constraints. Prefer returning entity URIs
   plus optional labels, not labels alone.

5. Multi-hop questions
   Examples: "Kể tên vị trí của những nhà sản xuất máy bay đã chọn Sukhoi Su-27
   để phát triển tiếp các model máy bay khác"
   Path: search_entity_by_label(start node) -> get_knowledgegraph_entry(start)
   -> identify intermediate relation/entity/class -> inspect intermediate node
   when needed -> execute_sparql with explicit multi-hop joins.
   Use the edge direction observed in get_knowledgegraph_entry. If a property is
   listed under the inspected entity's outgoing properties, write
   <inspected_entity> <property> ?value, not ?value <property>
   <inspected_entity>.

6. Comparison questions
   Examples: "Tàu khu trục lớp nào dài hơn: Type 055 hay Type 052D?"
   Path: search_entity_by_label(A) and search_entity_by_label(B) ->
   get_knowledgegraph_entry(A) and get_knowledgegraph_entry(B) -> use the same
   comparable property for both -> execute_sparql SELECT with both values or ASK
   if the question is yes/no.

7. Schema questions
   Examples: "Thuộc tính trần bay của một máy bay có tên đúng trong KB này là
   gì?", "Đâu là một loại hình công trình/tác phẩm phù hợp của Victor Hugo?"
   Path: search_property_by_label or search_class_by_label first. Then verify
   by execute_sparql with a small query or get_property_examples so the final
   answer is based on actual KB usage, not only search ranking.

8. Superlative questions
   Examples: "Công ty nào có số lượng nhân viên lớn nhất?", "Máy bay vận tải
   quân sự nào có số lượng sản xuất nhiều nhất?"
   Path: ground target classes and properties -> execute_sparql with numeric
   ORDER BY DESC(...) LIMIT 1. Use COUNT only when the question asks for number
   of matching entities; use ORDER BY when comparing attribute values.

SPARQL construction rules:
- Build the simplest executable query first, then add constraints.
- Prefer DBpedia ontology predicates/classes from dbo: over ad-hoc properties
  unless observed data requires otherwise.
- For final projections, do not return labels only. Return the actual URI/value
  variable.
- Do not use rdfs:label or rdfs:comment in generated SPARQL. The imported
  .ttl/.nt data in this GraphDB/Ontotext repository does not reliably contain
  those triples. Do not add label/comment lookups, do not use OPTIONAL label
  blocks, and do not use language tag filters such as LANG(...), lang(...), or
  FILTER(lang(...) = "en").
- If get_knowledgegraph_entry showed a value_label for a URI value, treat that
  label as display metadata from the tool. Query and project the underlying URI
  value directly in SPARQL.
- For "who/which entity" answers, SELECT ?entity or ?answer as the required
  projection. Do not create ?entityLabel variables.
- For dates, compare years with YEAR(xsd:dateTime(?date)) or STRSTARTS/STR when
  datatype is uncertain. Inspect examples first if needed.
- For numbers, cast with xsd:decimal/xsd:double only after checking the value
  shape. If units are ambiguous, inspect entity entries for both compared items.
- Any computed expression in SELECT must be wrapped and aliased with AS.
- This applies to aggregates, arithmetic expressions, casts, string/date
  functions, conditionals, and comparisons.
- Keep queries read-only. Use SELECT for entity/list/count/attribute/
  superlative/comparison answers and ASK for final true/false answers.

Backtracking and failure handling:
- Do not repeat the same tool call with the same arguments.
- If execute_sparql returns {"ok": false, ...}, inspect real edges/examples
  before rewriting the query.
- If execute_sparql returns [], treat it as a valid but empty query. Backtrack:
  inspect get_knowledgegraph_entry, try property examples, reconsider direction,
  class constraint, datatype, or exact entity grounding.
- If execute_sparql returns [] or rows with no bound values such as [{}],
  backtrack and retry by projecting real URI/value variables directly.
- execute_sparql returning a non-empty list with at least one bound value, or a
  boolean, is a valid execution result.
- Max iterations is 15. Use tools efficiently.

When done, return concise JSON only:
{
  "final_sparql": "...",
  "answer": "...",
  "result": ...
}
"""


class OntologyQAState(TypedDict, total=False):
    question: str
    messages: Annotated[list[AnyMessage], add_messages]
    steps: Annotated[list[dict[str, Any]], operator.add]
    actions: Annotated[list[dict[str, Any]], operator.add]
    generated_sparqls: Annotated[list[str], operator.add]
    executions: Annotated[list[dict[str, Any]], operator.add]
    last_execution_result: Any
    result: Any
    final_sparql: str | None
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
    executions = state.get("executions", [])
    last_execution = executions[-1] if executions else None

    messages = state.get("messages", [])
    final_payload: dict[str, Any] | None = None
    if messages and isinstance(messages[-1], AIMessage):
        final_payload = _extract_json_object(str(messages[-1].content))

    if last_execution and last_execution.get("ok"):
        final_sparql = str(last_execution.get("query", ""))
        result = last_execution.get("result")
        answer = str(messages[-1].content) if messages and isinstance(messages[-1], AIMessage) else ""
        if final_payload:
            answer = str(final_payload.get("answer") or "")
        return {
            "final_sparql": final_sparql,
            "answer": answer,
            "last_execution_result": result,
            "result": result,
        }

    answer = "No successful SPARQL execution was produced."
    if final_payload and final_payload.get("answer"):
        answer = str(final_payload["answer"])
    return {
        "final_sparql": None,
        "answer": answer,
        "result": state.get("last_execution_result"),
    }


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

    graph = StateGraph(OntologyQAState)
    graph.add_node("initialize", _initialize_node)
    graph.add_node("agent", _make_agent_node(chat_model))
    graph.add_node("tools", ToolNode(SEARCH_TOOLS + KG_TOOLS))
    graph.add_node("post_tool", _post_tool_node)
    graph.add_node("retry", _retry_node)
    graph.add_node("finalize", _finalize_node)

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
    "OntologyQAState",
    "build_ontology_qa_agent",
    "build_openrouter_chat_model",
]
