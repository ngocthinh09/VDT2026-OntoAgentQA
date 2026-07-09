from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas import TraceStep


SEARCH_TOOLS = {
    "search_entity",
    "search_entity_by_label",
    "search_property",
    "search_property_by_label",
    "search_class",
    "search_class_by_label",
}
INSPECT_TOOLS = {
    "get_knowledgegraph_entry",
    "get_property_examples",
}
EXECUTE_TOOLS = {
    "execute_sparql",
}


def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return make_json_safe(value.model_dump())
    if hasattr(value, "dict"):
        return make_json_safe(value.dict())
    return str(value)


def classify_tool(tool_name: str) -> str:
    if tool_name in SEARCH_TOOLS:
        return "search"
    if tool_name in INSPECT_TOOLS:
        return "inspect"
    if tool_name in EXECUTE_TOOLS:
        return "execute"
    return "tool"


def _tool_error(result: Any) -> str | None:
    if isinstance(result, Mapping) and result.get("ok") is False:
        return str(result.get("message") or result.get("error") or "Tool call failed")
    return None


def normalize_trace_steps(
    raw_steps: list[dict[str, Any]],
    *,
    start_index: int,
) -> list[TraceStep]:
    trace_steps: list[TraceStep] = []
    for offset, raw_step in enumerate(raw_steps):
        tool_name = str(raw_step.get("tool") or "")
        output = make_json_safe(raw_step.get("result"))
        error = _tool_error(output)
        trace_steps.append(
            TraceStep(
                step=start_index + offset,
                type=classify_tool(tool_name),
                tool=tool_name or None,
                input=make_json_safe(raw_step.get("args")),
                output=output,
                status="error" if error else "success",
                error=error,
            )
        )
    return trace_steps

