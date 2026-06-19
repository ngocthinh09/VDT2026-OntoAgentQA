from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ApiError, TransportError
from langchain_core.tools import tool


ENTITY_MODE = "entity"
SCHEMA_MODE = "schema"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _entity_index() -> str:
    return _env("ENTITY_INDEX", "entity_index")


def _schema_index() -> str:
    return _env("SCHEMA_INDEX", "schema_index")


@lru_cache(maxsize=1)
def get_es_client() -> Elasticsearch:
    """Create a cached Elasticsearch client from environment configuration."""
    return Elasticsearch(
        _env("ELASTICSEARCH_URL", "http://localhost:9200"),
        request_timeout=30,
        max_retries=3,
        retry_on_timeout=True,
    )


def _clamp_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(value, 50))


def _clean_query(query: str) -> str:
    return str(query or "").strip()


def _clean_fuzziness(fuzziness: str | None) -> str | None:
    if fuzziness is None:
        return None
    value = str(fuzziness).strip()
    return value or None


def _source_list(source: dict[str, Any], key: str) -> list[str]:
    value = source.get(key, [])
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []


def _normalize_hit(hit: dict[str, Any], mode: Literal["entity", "schema"]) -> dict[str, Any]:
    source = hit.get("_source", {})
    score = hit.get("_score")

    if mode == ENTITY_MODE:
        return {
            "label": source.get("label", ""),
            "uri": source.get("uri", ""),
            "score": score,
            "types": _source_list(source, "types"),
            "type_labels": _source_list(source, "type_labels"),
        }

    labels = _source_list(source, "labels")
    return {
        "label": labels[0] if labels else "",
        "uri": source.get("uri", ""),
        "kind": source.get("kind", ""),
        "score": score,
        "comments": _source_list(source, "comments"),
        "domain": source.get("domain", ""),
        "range": source.get("range", ""),
        "domain_label": source.get("domain_label", ""),
        "range_label": source.get("range_label", ""),
    }


def _search_entity(
    query: str,
    limit: int = 10,
    fuzziness: str | None = "AUTO",
) -> list[dict[str, Any]]:
    clean_query = _clean_query(query)
    if not clean_query:
        return []

    multi_match: dict[str, Any] = {
        "query": clean_query,
        "fields": ["label^4", "type_labels"],
    }
    clean_fuzziness = _clean_fuzziness(fuzziness)
    if clean_fuzziness:
        multi_match["fuzziness"] = clean_fuzziness

    body = {
        "query": {
            "multi_match": multi_match
        }
    }

    try:
        response = get_es_client().search(
            index=_entity_index(),
            size=_clamp_limit(limit),
            query=body["query"],
        )
    except (ApiError, TransportError) as exc:
        raise RuntimeError(f"Elasticsearch search failed: {exc}") from exc

    hits = response.get("hits", {}).get("hits", [])
    return [_normalize_hit(hit, ENTITY_MODE) for hit in hits]


def _search_schema(
    query: str,
    kind: Literal["property", "class"],
    limit: int = 10,
    fuzziness: str | None = "AUTO",
) -> list[dict[str, Any]]:
    clean_query = _clean_query(query)
    if not clean_query:
        return []

    fields = ["labels^4", "comments"]
    if kind == "property":
        fields.extend(["domain_label", "range_label"])

    multi_match: dict[str, Any] = {
        "query": clean_query,
        "fields": fields,
    }
    clean_fuzziness = _clean_fuzziness(fuzziness)
    if clean_fuzziness:
        multi_match["fuzziness"] = clean_fuzziness

    body = {
        "query": {
            "bool": {
                "filter": [{"term": {"kind": kind}}],
                "must": {
                    "multi_match": multi_match
                },
            }
        }
    }

    try:
        response = get_es_client().search(
            index=_schema_index(),
            size=_clamp_limit(limit),
            query=body["query"],
        )
    except (ApiError, TransportError) as exc:
        raise RuntimeError(f"Elasticsearch search failed: {exc}") from exc

    hits = response.get("hits", {}).get("hits", [])
    return [_normalize_hit(hit, SCHEMA_MODE) for hit in hits]


@tool
def search_entity_by_label(
    query: str,
    limit: int = 10,
    fuzziness: str | None = "AUTO",
) -> list[dict[str, Any]]:
    """Search DBpedia named entities/instances by lexical label.

    Use this tool when the question mentions a concrete resource that should
    become a SPARQL entity URI, such as a person, place, organization, creative
    work, event, or other named instance. This tool searches only the entity
    index.

    Args:
        query: Entity name or phrase to search for, for example
            "Albert Einstein", "Hanoi", or "The Godfather". Blank or
            whitespace-only queries return an empty list.
        limit: Maximum number of matches to return. Values are clamped to the
            range 1..50. Defaults to 10.
        fuzziness: Elasticsearch fuzzy matching setting for the multi_match
            query. Defaults to "AUTO". Pass None or an empty string to disable.

    Returns:
        A list of result dictionaries sorted by Elasticsearch relevance score.
        Each dictionary has this format:
        {
            "label": "Albert Einstein",
            "uri": "http://dbpedia.org/resource/Albert_Einstein",
            "score": 12.3,
            "types": ["http://dbpedia.org/ontology/Scientist"],
            "type_labels": ["Scientist"]
        }
    """
    return _search_entity(query, limit, fuzziness)


@tool
def search_property_by_label(
    query: str,
    limit: int = 10,
    fuzziness: str | None = "AUTO",
) -> list[dict[str, Any]]:
    """Search DBpedia ontology properties by label or description.

    Use this tool when the question needs a SPARQL predicate/relation/attribute,
    such as birth place, birth year, author, starring, population, or area. This
    tool searches the schema index and returns only documents with
    kind="property".

    Args:
        query: Property label, relation phrase, or attribute phrase to search
            for, for example "birth year", "director", or "population total".
            Blank or whitespace-only queries return an empty list.
        limit: Maximum number of matches to return. Values are clamped to the
            range 1..50. Defaults to 10.
        fuzziness: Elasticsearch fuzzy matching setting for the multi_match
            query. Defaults to "AUTO". Pass None or an empty string to disable.

    Returns:
        A list of result dictionaries sorted by Elasticsearch relevance score.
        Each dictionary has this format:
        {
            "label": "birth year",
            "uri": "http://dbpedia.org/ontology/birthYear",
            "kind": "property",
            "score": 10.5,
            "comments": [],
            "domain": "http://dbpedia.org/ontology/Person",
            "range": "http://www.w3.org/2001/XMLSchema#gYear",
            "domain_label": "Person",
            "range_label": "g Year"
        }
    """
    return _search_schema(query, "property", limit, fuzziness)


@tool
def search_class_by_label(
    query: str,
    limit: int = 5,
    fuzziness: str | None = "AUTO",
) -> list[dict[str, Any]]:
    """Search DBpedia ontology classes by label or description.

    Use this tool when the question needs an ontology type/category for an
    rdf:type constraint, such as actor, city, film, university, country, or
    scientist. This tool searches the schema index and returns only documents
    with kind="class".

    Args:
        query: Class/type/category label to search for, for example "actor",
            "film", "city", or "university". Blank or whitespace-only queries
            return an empty list.
        limit: Maximum number of matches to return. Values are clamped to the
            range 1..50. Defaults to 10.
        fuzziness: Elasticsearch fuzzy matching setting for the multi_match
            query. Defaults to "AUTO". Pass None or an empty string to disable.

    Returns:
        A list of result dictionaries sorted by Elasticsearch relevance score.
        Each dictionary has this format:
        {
            "label": "Actor",
            "uri": "http://dbpedia.org/ontology/Actor",
            "kind": "class",
            "score": 9.8,
            "comments": ["An actor or actress is a person who acts..."],
            "domain": "",
            "range": "",
            "domain_label": "",
            "range_label": ""
        }
    """
    return _search_schema(query, "class", limit, fuzziness)


def format_search_results(results: list[dict[str, Any]]) -> str:
    """Format structured search results into compact observation text."""
    if not results:
        return "No results."

    lines: list[str] = []
    for idx, result in enumerate(results, start=1):
        label = result.get("label") or "(no label)"
        uri = result.get("uri") or "(no uri)"
        score = result.get("score")
        kind = result.get("kind")
        prefix = f"{idx}. {label} <{uri}>"
        if kind:
            prefix += f" [{kind}]"
        if score is not None:
            prefix += f" score={score:.3f}" if isinstance(score, float) else f" score={score}"
        lines.append(prefix)
    return "\n".join(lines)


SEARCH_TOOLS = [
    search_entity_by_label,
    search_property_by_label,
    search_class_by_label,
]
