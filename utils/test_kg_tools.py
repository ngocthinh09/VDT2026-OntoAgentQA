from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.kg_tools import (
    _clamp_limit,
    execute_sparql,
    format_kg_entry,
    format_property_examples,
    get_knowledgegraph_entry,
    get_property_examples,
)


def _invoke(tool: Any, **kwargs: Any) -> Any:
    if hasattr(tool, "invoke"):
        return tool.invoke(kwargs)
    return tool(**kwargs)


def _assert_entry(name: str, entry: dict[str, Any]) -> None:
    assert entry, f"{name} returned no entry"
    assert entry.get("entity", {}).get("uri"), f"{name} has no entity uri"
    assert entry.get("properties"), f"{name} returned no properties"

    first_property = entry["properties"][0]
    assert first_property.get("property_label"), f"{name} property has no usable label"
    assert first_property.get("values"), f"{name} first property has no values"
    assert first_property["values"][0].get("value_label"), f"{name} value has no usable label"


def _assert_examples(name: str, examples: list[dict[str, Any]]) -> None:
    assert examples, f"{name} returned no examples"
    first = examples[0]
    assert first.get("subject_uri"), f"{name} first example has no subject uri"
    assert first.get("property_uri"), f"{name} first example has no property uri"
    assert first.get("object"), f"{name} first example has no object"
    assert first.get("subject_label"), f"{name} first example has no subject label"
    assert first.get("property_label"), f"{name} first example has no property label"
    assert first.get("object_label"), f"{name} first example has no object label"


def main() -> int:
    assert _invoke(execute_sparql, query="") == []
    assert _invoke(
        execute_sparql,
        query="ASK { <http://dbpedia.org/resource/Albert_Einstein> ?p ?o }",
    ) is True
    assert _invoke(
        execute_sparql,
        query="ASK { dbr:Albert_Einstein ?p ?o }",
    ) is True
    sparql_error = _invoke(execute_sparql, query="SELECT WHERE {")
    assert sparql_error["ok"] is False
    assert sparql_error["error_type"] == "sparql_execution_error"
    assert _invoke(get_knowledgegraph_entry, entity_uri="", limit=100) == {}
    assert _invoke(get_property_examples, property_uri="", limit=5) == []
    assert _clamp_limit(999, 200, 500) == 500
    assert _clamp_limit(999, 5, 20) == 20

    print("Knowledge graph entry by URI test:")
    entry_by_uri = _invoke(
        get_knowledgegraph_entry,
        entity_uri="http://dbpedia.org/resource/Albert_Einstein",
        limit=100,
    )
    print(format_kg_entry(entry_by_uri))
    _assert_entry("entry by uri", entry_by_uri)

    print("Knowledge graph entry by label test:")
    entry_by_label = _invoke(
        get_knowledgegraph_entry,
        entity_uri="Albert Einstein",
        limit=100,
    )
    print(format_kg_entry(entry_by_label))
    _assert_entry("entry by label", entry_by_label)
    assert (
        entry_by_label["entity"]["uri"] == "http://dbpedia.org/resource/Albert_Einstein"
    )

    print("Property examples by local name test:")
    examples_by_name = _invoke(
        get_property_examples,
        property_uri="birthPlace",
        limit=5,
    )
    print(format_property_examples(examples_by_name))
    _assert_examples("examples by local name", examples_by_name)

    print("Property examples by URI test:")
    examples_by_uri = _invoke(
        get_property_examples,
        property_uri="http://dbpedia.org/ontology/birthPlace",
        limit=5,
    )
    print(format_property_examples(examples_by_uri))
    _assert_examples("examples by uri", examples_by_uri)

    print("Knowledge graph tools smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
