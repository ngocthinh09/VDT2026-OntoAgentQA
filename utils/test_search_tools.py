"""Smoke test for the LangChain Elasticsearch search tools.

Run with:
    python -m utils.test_search_tools
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.search_tools import (
    _clamp_limit,
    search_class_by_label,
    search_entity_by_label,
    search_property_by_label,
)


def _invoke(tool: Any, query: str, limit: int) -> list[dict[str, Any]]:
    if hasattr(tool, "invoke"):
        return tool.invoke({"query": query, "limit": limit})
    return tool(query, limit)


def _assert_non_empty_with_uri(name: str, results: list[dict[str, Any]]) -> None:
    assert results, f"{name} returned no results"
    assert results[0].get("uri"), f"{name} first result has no uri"


def main() -> int:
    assert _invoke(search_entity_by_label, "", 5) == []
    assert _clamp_limit(999) == 50

    print("Separate entity search test:")

    entity_results = _invoke(search_entity_by_label, "Albert Einstein", 5)
    print(f"Entity search results: {entity_results}")
    _assert_non_empty_with_uri("entity search", entity_results)

    print("Separate property search test:")

    property_results = _invoke(search_property_by_label, "birth year", 5)
    print(f"Property search results: {property_results}")
    _assert_non_empty_with_uri("property search", property_results)
    assert all(result.get("kind") == "property" for result in property_results)

    print("Separate class search test:")

    class_results = _invoke(search_class_by_label, "actor", 5)
    print(f"Class search results: {class_results}")
    _assert_non_empty_with_uri("class search", class_results)
    assert all(result.get("kind") == "class" for result in class_results)
    
    print("Search tools smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
