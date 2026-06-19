from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Any
from urllib.parse import unquote

import requests
from langchain_core.tools import tool


GRAPHDB_ENDPOINT = os.environ.get(
    "GRAPHDB_ENDPOINT",
    "http://35.254.39.200:7200/repositories/DBPEDIA",
)
GRAPHDB_TIMEOUT = int(os.environ.get("GRAPHDB_TIMEOUT", "30"))

DBR_PREFIX = "http://dbpedia.org/resource/"
DBO_PREFIX = "http://dbpedia.org/ontology/"

KNOWN_SPARQL_PREFIXES = {
    "dbr": "http://dbpedia.org/resource/",
    "dbo": "http://dbpedia.org/ontology/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}

SPARQL_PREFIXES = """\
PREFIX dbr: <http://dbpedia.org/resource/>
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
"""

SPARQL_AGGREGATE_PATTERN = re.compile(
    r"(?i)\b(COUNT|SUM|MIN|MAX|AVG|SAMPLE|GROUP_CONCAT)\s*\("
)


def _execute_sparql(query: str) -> list[dict[str, Any]] | bool:
    """Execute a SELECT/ASK SPARQL query against GraphDB."""
    try:
        response = requests.get(
            GRAPHDB_ENDPOINT,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            timeout=GRAPHDB_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"GraphDB SPARQL query failed: {exc}") from exc

    if "boolean" in payload:
        return bool(payload["boolean"])

    return payload.get("results", {}).get("bindings", [])


def _add_missing_prefixes(query: str) -> str:
    prefixes_to_add: list[str] = []
    for prefix, uri in KNOWN_SPARQL_PREFIXES.items():
        prefix_declared = re.search(rf"(?im)^\s*PREFIX\s+{re.escape(prefix)}\s*:", query)
        prefix_used = re.search(rf"(?<![A-Za-z0-9_-]){re.escape(prefix)}:", query)
        if prefix_used and not prefix_declared:
            prefixes_to_add.append(f"PREFIX {prefix}: <{uri}>")

    if not prefixes_to_add:
        return query
    return "\n".join(prefixes_to_add) + "\n" + query


def _sparql_error_result(error_type: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_type": error_type,
        "message": message,
    }


def _sparql_operation(query: str) -> str:
    clean_query = _clean_input(query)
    clean_query = re.sub(r"(?m)^\s*#.*$", "", clean_query).strip()

    prefix_pattern = re.compile(
        r"(?is)^(?:PREFIX\s+[A-Za-z][\w-]*:\s*<[^>]+>|BASE\s*<[^>]+>)\s*"
    )
    while True:
        match = prefix_pattern.match(clean_query)
        if not match:
            break
        clean_query = clean_query[match.end() :].lstrip()

    match = re.match(r"(?is)^([A-Za-z]+)\b", clean_query)
    return match.group(1).upper() if match else ""


def _mask_sparql_non_code(query: str) -> str:
    """Mask comments, string literals, and IRI references while preserving offsets."""
    chars = list(query)
    length = len(query)
    index = 0

    def mask(start: int, end: int) -> None:
        for position in range(start, min(end, length)):
            if chars[position] not in {"\n", "\r"}:
                chars[position] = " "

    while index < length:
        if query[index] == "#":
            end = query.find("\n", index)
            end = length if end == -1 else end
            mask(index, end)
            index = end
            continue

        if query.startswith(('"""', "'''"), index):
            quote = query[index : index + 3]
            end = index + 3
            while end < length:
                if query.startswith(quote, end):
                    end += 3
                    break
                if query[end] == "\\":
                    end += 2
                else:
                    end += 1
            mask(index, end)
            index = end
            continue

        if query[index] in {'"', "'"}:
            quote = query[index]
            end = index + 1
            while end < length:
                if query[end] == "\\":
                    end += 2
                    continue
                end += 1
                if query[end - 1] == quote:
                    break
            mask(index, end)
            index = end
            continue

        if query[index] == "<" and re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", query[index + 1 :]):
            end = query.find(">", index + 1)
            end = length if end == -1 else end + 1
            mask(index, end)
            index = end
            continue

        index += 1

    return "".join(chars)


def _select_projection_ranges(masked_query: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"(?i)\bSELECT\b", masked_query):
        start = match.end()
        depth = 0
        index = start
        while index < len(masked_query):
            char = masked_query[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                if char == "{":
                    ranges.append((start, index))
                    break
                where_match = re.match(r"(?i)WHERE\b", masked_query[index:])
                if where_match:
                    ranges.append((start, index))
                    break
            index += 1
    return ranges


def _projection_group_has_alias(projection: str, group_start: int, group_end: int) -> bool:
    depth = 0
    index = group_start
    while index < group_end:
        char = projection[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 1:
            alias_match = re.match(r"(?i)\bAS\s+\?[A-Za-z_][A-Za-z0-9_]*", projection[index:])
            if alias_match:
                return True
        index += 1
    return False


def _aggregate_alias_error(query: str) -> str | None:
    """Return an actionable error when a SELECT aggregate lacks an AS alias."""
    masked_query = _mask_sparql_non_code(query)
    invalid_aggregates: list[str] = []

    for start, end in _select_projection_ranges(masked_query):
        projection = masked_query[start:end]
        group_stack: list[int] = []
        top_level_groups: list[tuple[int, int]] = []
        for index, char in enumerate(projection):
            if char == "(":
                group_stack.append(index)
            elif char == ")" and group_stack:
                group_start = group_stack.pop()
                if not group_stack:
                    top_level_groups.append((group_start, index + 1))

        for aggregate_match in SPARQL_AGGREGATE_PATTERN.finditer(projection):
            aggregate_position = aggregate_match.start()
            enclosing_group = next(
                (
                    (group_start, group_end)
                    for group_start, group_end in top_level_groups
                    if group_start < aggregate_position < group_end
                ),
                None,
            )
            if enclosing_group is None or not _projection_group_has_alias(
                projection, *enclosing_group
            ):
                invalid_aggregates.append(aggregate_match.group(1).upper())

    if not invalid_aggregates:
        return None

    aggregate_names = ", ".join(dict.fromkeys(invalid_aggregates))
    return (
        f"Aggregate expression(s) {aggregate_names} in SELECT must be wrapped "
        "and aliased with AS. Example: SELECT (COUNT(?item) AS ?count) "
        "WHERE { ... }"
    )


def _clamp_limit(limit: int, default: int, upper: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, upper))


def _clean_input(value: str) -> str:
    return str(value or "").strip()


def _local_name(uri: str) -> str:
    value = str(uri or "").strip()
    if not value:
        return ""

    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]

    local = re.split(r"[/#]", value.rstrip("/#"))[-1]
    return unquote(local)


def _readable_local_name(value: str) -> str:
    local = _local_name(value)
    if not local:
        return ""

    local = local.replace("_", " ").replace("-", " ")
    local = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local)
    local = re.sub(r"\s+", " ", local).strip()
    return local


def _looks_like_uri(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _strip_uri_ref(value: str) -> str:
    clean = _clean_input(value)
    if clean.startswith("<") and clean.endswith(">"):
        return clean[1:-1]
    if clean.startswith("dbr:"):
        return DBR_PREFIX + clean[len("dbr:") :]
    if clean.startswith("dbo:"):
        return DBO_PREFIX + clean[len("dbo:") :]
    if _looks_like_uri(clean):
        return clean
    return clean


def _normalize_entity_ref(entity_uri: str) -> str:
    clean = _clean_input(entity_uri)
    if not clean:
        return ""
    if clean.startswith("<") and clean.endswith(">"):
        return clean
    if _looks_like_uri(clean):
        return f"<{clean}>"
    if clean.startswith("dbr:"):
        return clean
    return "dbr:" + clean.replace(" ", "_")


def _normalize_property_ref(property_uri: str) -> str:
    clean = _clean_input(property_uri)
    if not clean:
        return ""
    if clean.startswith("<") and clean.endswith(">"):
        return clean
    if _looks_like_uri(clean):
        return f"<{clean}>"
    if clean.startswith("dbo:"):
        return clean
    return "dbo:" + clean


def _binding_value(binding: dict[str, Any], key: str) -> str:
    return str(binding.get(key, {}).get("value", ""))


def _binding_type(binding: dict[str, Any], key: str) -> str:
    return str(binding.get(key, {}).get("type", "literal"))


def _display_label(value: str, value_type: str = "uri") -> str:
    if value_type == "uri" and (_looks_like_uri(value) or value.startswith("<")):
        return _readable_local_name(value)
    return str(value)


def _label_or_fallback(label: str, uri_or_value: str, value_type: str = "uri") -> str:
    clean_label = str(label or "").strip()
    if clean_label and not _looks_like_uri(clean_label):
        return clean_label
    return _display_label(uri_or_value, value_type)


def _knowledgegraph_entry_query(entity_ref: str, limit: int) -> str:
    return f"""{SPARQL_PREFIXES}
SELECT ?p ?v ?pLabel ?vLabel
WHERE {{
  {entity_ref} ?p ?v .

  FILTER(?p NOT IN (
    rdfs:comment,
    rdfs:label,
    rdfs:isDefinedBy,
    foaf:depiction,
    rdfs:subClassOf
  ))

  OPTIONAL {{
    ?p rdfs:label ?pLabelRaw .
    FILTER(LANG(?pLabelRaw) = "en" || LANG(?pLabelRaw) = "")
  }}

  BIND(
    IF(
      ?p = rdf:type,
      "is a",
      COALESCE(?pLabelRaw, STR(?p))
    ) AS ?pLabel
  )

  OPTIONAL {{
    ?v rdfs:label ?vLabelRdfsEn .
    FILTER(LANG(?vLabelRdfsEn) = "en")
  }}

  OPTIONAL {{
    ?v rdfs:label ?vLabelRdfsNoLang .
    FILTER(LANG(?vLabelRdfsNoLang) = "")
  }}

  OPTIONAL {{
    ?v foaf:name ?vNameEn .
    FILTER(LANG(?vNameEn) = "en")
  }}

  OPTIONAL {{
    ?v foaf:name ?vNameNoLang .
    FILTER(LANG(?vNameNoLang) = "")
  }}

  BIND(
    COALESCE(
      ?vLabelRdfsEn,
      ?vLabelRdfsNoLang,
      ?vNameEn,
      ?vNameNoLang,
      STR(?v)
    ) AS ?vLabel
  )
}}
LIMIT {limit}
"""


def _property_examples_query(property_ref: str, limit: int) -> str:
    return f"""{SPARQL_PREFIXES}
SELECT DISTINCT
  ?subject
  ?subjectLabel
  ?object
  ?objectLabel
  ?propertyLabel
WHERE {{
  ?subject {property_ref} ?object .

  OPTIONAL {{
    {property_ref} rdfs:label ?propertyLabelRaw .
    FILTER(LANG(?propertyLabelRaw) = "en" || LANG(?propertyLabelRaw) = "")
  }}
  BIND(COALESCE(?propertyLabelRaw, STR({property_ref})) AS ?propertyLabel)

  OPTIONAL {{
    ?subject rdfs:label ?subjectRdfsEn .
    FILTER(LANG(?subjectRdfsEn) = "en")
  }}
  OPTIONAL {{
    ?subject rdfs:label ?subjectRdfsNoLang .
    FILTER(LANG(?subjectRdfsNoLang) = "")
  }}
  OPTIONAL {{
    ?subject foaf:name ?subjectNameEn .
    FILTER(LANG(?subjectNameEn) = "en")
  }}
  OPTIONAL {{
    ?subject foaf:name ?subjectNameNoLang .
    FILTER(LANG(?subjectNameNoLang) = "")
  }}
  BIND(
    COALESCE(
      ?subjectRdfsEn,
      ?subjectRdfsNoLang,
      ?subjectNameEn,
      ?subjectNameNoLang,
      STR(?subject)
    ) AS ?subjectLabel
  )

  OPTIONAL {{
    ?object rdfs:label ?objectRdfsEn .
    FILTER(LANG(?objectRdfsEn) = "en")
  }}
  OPTIONAL {{
    ?object rdfs:label ?objectRdfsNoLang .
    FILTER(LANG(?objectRdfsNoLang) = "")
  }}
  OPTIONAL {{
    ?object foaf:name ?objectNameEn .
    FILTER(LANG(?objectNameEn) = "en")
  }}
  OPTIONAL {{
    ?object foaf:name ?objectNameNoLang .
    FILTER(LANG(?objectNameNoLang) = "")
  }}
  BIND(
    COALESCE(
      ?objectRdfsEn,
      ?objectRdfsNoLang,
      ?objectNameEn,
      ?objectNameNoLang,
      STR(?object)
    ) AS ?objectLabel
  )
}}
LIMIT {limit}
"""


@tool
def execute_sparql(query: str) -> list[dict[str, Any]] | bool | dict[str, Any]:
    """Execute a read-only SPARQL query against the configured GraphDB repository.

    Use this tool only when the task requires a custom SPARQL query that is not
    covered by the higher-level knowledge graph tools. The query must be a
    SELECT or ASK query. Update operations such as INSERT, DELETE, CLEAR, DROP,
    LOAD, CREATE, and MOVE are rejected.

    Args:
        query: Complete SPARQL SELECT or ASK query. Blank input returns [].

    Returns:
        SELECT queries return GraphDB binding dictionaries. ASK queries return
        a boolean. Invalid or failed queries return an error dictionary with
        ok=false, error_type, and message, so this is distinct from an empty
        successful SELECT result [].
    """
    clean_query = _clean_input(query)
    if not clean_query:
        return []

    query_with_prefixes = _add_missing_prefixes(clean_query)
    operation = _sparql_operation(query_with_prefixes)
    if operation not in {"SELECT", "ASK"}:
        return _sparql_error_result(
            "unsupported_operation",
            "execute_sparql only supports read-only SELECT or ASK queries.",
        )

    aggregate_alias_error = _aggregate_alias_error(query_with_prefixes)
    if aggregate_alias_error:
        return _sparql_error_result(
            "aggregate_alias_required",
            aggregate_alias_error,
        )

    try:
        return _execute_sparql(query_with_prefixes)
    except RuntimeError as exc:
        return _sparql_error_result("sparql_execution_error", str(exc))


@tool
def get_knowledgegraph_entry(entity_uri: str, limit: int = 200) -> dict[str, Any]:
    """Return outgoing DBpedia facts for one entity.

    Use this tool after identifying a concrete DBpedia resource URI or entity
    name and you need to inspect its available predicates and values.

    Args:
        entity_uri: DBpedia resource URI, prefixed name, or plain entity label.
            Examples: "http://dbpedia.org/resource/Albert_Einstein",
            "dbr:Albert_Einstein", or "Albert Einstein". Blank input returns
            an empty dictionary.
        limit: Maximum number of triples to read. Values are clamped to 1..500.

    Returns:
        A dictionary with an entity block and grouped outgoing properties.
    """
    clean_input = _clean_input(entity_uri)
    entity_ref = _normalize_entity_ref(clean_input)
    if not entity_ref:
        return {}

    normalized_uri = _strip_uri_ref(entity_ref)
    query = _knowledgegraph_entry_query(entity_ref, _clamp_limit(limit, 200, 500))
    rows = _execute_sparql(query)
    if isinstance(rows, bool):
        rows = []

    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for row in rows:
        property_uri = _binding_value(row, "p")
        value = _binding_value(row, "v")
        value_type = "uri" if _binding_type(row, "v") == "uri" else "literal"
        property_label = _label_or_fallback(
            _binding_value(row, "pLabel"),
            property_uri,
            "uri",
        )
        value_label = _label_or_fallback(
            _binding_value(row, "vLabel"),
            value,
            value_type,
        )

        if property_uri not in grouped:
            grouped[property_uri] = {
                "property_label": property_label,
                "property_uri": property_uri,
                "values": [],
            }

        grouped[property_uri]["values"].append(
            {
                "value_label": value_label,
                "value": value,
                "value_type": value_type,
            }
        )

    return {
        "entity": {
            "input": clean_input,
            "uri": normalized_uri,
            "label": _readable_local_name(normalized_uri),
        },
        "properties": list(grouped.values()),
    }


@tool
def get_property_examples(property_uri: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return example triples for one DBpedia ontology property.

    Use this tool after identifying a DBpedia property URI or property name and
    you need concrete subject-object examples for that predicate.

    Args:
        property_uri: DBpedia ontology property URI, prefixed name, or local
            property name. Examples: "http://dbpedia.org/ontology/birthPlace",
            "dbo:birthPlace", or "birthPlace". Blank input returns [].
        limit: Maximum number of examples to return. Values are clamped to 1..20.

    Returns:
        A list of dictionaries containing subject, property, and object fields.
    """
    property_ref = _normalize_property_ref(property_uri)
    if not property_ref:
        return []

    normalized_uri = _strip_uri_ref(property_ref)
    query = _property_examples_query(property_ref, _clamp_limit(limit, 5, 20))
    rows = _execute_sparql(query)
    if isinstance(rows, bool):
        rows = []

    examples: list[dict[str, Any]] = []
    for row in rows:
        subject_uri = _binding_value(row, "subject")
        object_value = _binding_value(row, "object")
        object_type = "uri" if _binding_type(row, "object") == "uri" else "literal"

        examples.append(
            {
                "subject_label": _label_or_fallback(
                    _binding_value(row, "subjectLabel"),
                    subject_uri,
                    "uri",
                ),
                "subject_uri": subject_uri,
                "property_label": _label_or_fallback(
                    _binding_value(row, "propertyLabel"),
                    normalized_uri,
                    "uri",
                ),
                "property_uri": normalized_uri,
                "object_label": _label_or_fallback(
                    _binding_value(row, "objectLabel"),
                    object_value,
                    object_type,
                ),
                "object": object_value,
                "object_type": object_type,
            }
        )

    return examples


def format_kg_entry(entry: dict[str, Any]) -> str:
    """Format a knowledge graph entry into compact observation text."""
    if not entry:
        return "No entry."

    entity = entry.get("entity", {})
    lines = [
        f"{entity.get('label') or entity.get('input') or '(unknown entity)'} "
        f"<{entity.get('uri') or '(no uri)'}>"
    ]

    for prop in entry.get("properties", []):
        values = prop.get("values", [])
        rendered_values = ", ".join(
            f"{value.get('value_label') or value.get('value')} <{value.get('value')}>"
            if value.get("value_type") == "uri"
            else str(value.get("value_label") or value.get("value"))
            for value in values
        )
        lines.append(
            f"- {prop.get('property_label') or '(no property label)'} "
            f"<{prop.get('property_uri') or '(no property uri)'}>: {rendered_values}"
        )

    return "\n".join(lines)


def format_property_examples(examples: list[dict[str, Any]]) -> str:
    """Format property example triples into compact observation text."""
    if not examples:
        return "No examples."

    lines: list[str] = []
    for idx, example in enumerate(examples, start=1):
        subject = f"{example.get('subject_label') or '(no subject)'} <{example.get('subject_uri')}>"
        predicate = f"{example.get('property_label') or '(no property)'} <{example.get('property_uri')}>"
        if example.get("object_type") == "uri":
            obj = f"{example.get('object_label') or '(no object)'} <{example.get('object')}>"
        else:
            obj = str(example.get("object_label") or example.get("object"))
        lines.append(f"{idx}. {subject} -- {predicate} --> {obj}")
    return "\n".join(lines)


KG_TOOLS = [
    execute_sparql,
    get_knowledgegraph_entry,
    get_property_examples,
]
