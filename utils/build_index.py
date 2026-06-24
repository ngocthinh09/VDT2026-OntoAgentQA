import os
import re
import sys
from collections import defaultdict
from typing import Any, Iterator
from urllib.parse import unquote

from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm


ES_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
ENTITY_INDEX = os.environ.get("ENTITY_INDEX", "entity_index")
SCHEMA_INDEX = os.environ.get("SCHEMA_INDEX", "schema_index")

DATA_DIR = os.environ.get("DATA_DIR", "data")
INSTANCE_FILE = os.environ.get("INSTANCE_FILE", os.path.join(DATA_DIR, "instance-types.ttl"))
ONTOLOGY_FILE = os.environ.get("ONTOLOGY_FILE", os.path.join(DATA_DIR, "ontology--DEV_type=parsed_sorted.nt"))

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
RDFS_DOMAIN = "http://www.w3.org/2000/01/rdf-schema#domain"
RDFS_RANGE = "http://www.w3.org/2000/01/rdf-schema#range"
OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"
OWL_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#ObjectProperty"
OWL_DATATYPE_PROPERTY = "http://www.w3.org/2002/07/owl#DatatypeProperty"
RDF_PROPERTY = "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property"

SCHEMA_TYPES = {
    OWL_CLASS: "class",
    OWL_OBJECT_PROPERTY: "property",
    OWL_DATATYPE_PROPERTY: "property",
    RDF_PROPERTY: "property",
}

TRIPLE_RE = re.compile(r"^\s*<([^>]+)>\s+<([^>]+)>\s+(.+?)\s*\.\s*$")
CAMEL_RE_1 = re.compile(r"([a-z0-9])([A-Z])")
CAMEL_RE_2 = re.compile(r"([A-Z]+)([A-Z][a-z])")
ESCAPE_RE = re.compile(r"\\(u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)")


def connect_es() -> Elasticsearch:
    return Elasticsearch(
        ES_URL,
        request_timeout=60,
        max_retries=3,
        retry_on_timeout=True,
    )


es = connect_es()


def decode_nt_escape(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("u") or token.startswith("U"):
            return chr(int(token[1:], 16))
        return {
            "t": "\t",
            "b": "\b",
            "n": "\n",
            "r": "\r",
            "f": "\f",
            '"': '"',
            "'": "'",
            "\\": "\\",
        }.get(token, token)

    return ESCAPE_RE.sub(replace, value)


def split_words(value: str) -> str:
    value = unquote(value)
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = CAMEL_RE_2.sub(r"\1 \2", value)
    value = CAMEL_RE_1.sub(r"\1 \2", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def local_name(uri: str) -> str:
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rsplit("/", 1)[-1]


def ontology_local_name(uri: str) -> str:
    prefix = "http://dbpedia.org/ontology/"
    if uri.startswith(prefix):
        return uri[len(prefix) :]
    return local_name(uri)


def derive_entity_label(uri: str) -> tuple[str, str]:
    raw = local_name(uri)
    return split_words(raw), raw


def derive_schema_label(uri: str) -> tuple[str, str]:
    raw = ontology_local_name(uri)
    return split_words(raw), raw


def parse_object(object_part: str) -> tuple[str, bool, str | None]:
    object_part = object_part.strip()
    if object_part.startswith("<"):
        end = object_part.find(">")
        if end < 0:
            raise ValueError(f"Malformed URI object: {object_part}")
        return object_part[1:end], False, None

    if not object_part.startswith('"'):
        return object_part, False, None

    escaped = False
    end = -1
    for idx in range(1, len(object_part)):
        char = object_part[idx]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            end = idx
            break

    if end < 0:
        raise ValueError(f"Malformed literal object: {object_part}")

    literal = decode_nt_escape(object_part[1:end])
    suffix = object_part[end + 1 :].strip()
    lang = None
    if suffix.startswith("@"):
        lang = suffix[1:].split()[0].lower()
    return literal, True, lang


def parse_nt_line(line: str) -> tuple[str, str, str, bool, str | None] | None:
    match = TRIPLE_RE.match(line)
    if not match:
        return None

    subject = match.group(1)
    predicate = match.group(2)
    obj, is_literal, lang = parse_object(match.group(3))
    return subject, predicate, obj, is_literal, lang


def unique_append(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def init_indices() -> None:
    for index in (ENTITY_INDEX, SCHEMA_INDEX):
        if es.indices.exists(index=index):
            es.indices.delete(index=index)

    common_settings = {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "refresh_interval": "-1",
        "analysis": {
            "filter": {
                "english_possessive_stemmer": {
                    "type": "stemmer",
                    "language": "possessive_english",
                },
                "english_stemmer": {
                    "type": "stemmer",
                    "language": "english",
                },
            },
            "normalizer": {
                "lowercase_normalizer": {
                    "type": "custom",
                    "filter": ["lowercase", "asciifolding"],
                }
            },
            "analyzer": {
                "folding_text": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                "english_stemmed_text": {
                    "tokenizer": "standard",
                    "filter": [
                        "english_possessive_stemmer",
                        "lowercase",
                        "asciifolding",
                        "english_stemmer",
                    ],
                }
            },
        },
    }

    es.indices.create(
        index=ENTITY_INDEX,
        settings=common_settings,
        mappings={
            "properties": {
                "uri": {"type": "keyword"},
                "label": {
                    "type": "text",
                    "analyzer": "folding_text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "normalizer": "lowercase_normalizer",
                        }
                    },
                },
                "raw_local_name": {"type": "keyword"},
                "types": {"type": "keyword"},
                "type_labels": {"type": "text", "analyzer": "folding_text"},
            }
        },
    )

    es.indices.create(
        index=SCHEMA_INDEX,
        settings=common_settings,
        mappings={
            "properties": {
                "uri": {"type": "keyword"},
                "kind": {"type": "keyword"},
                "labels": {
                    "type": "text",
                    "analyzer": "english_stemmed_text",
                    "search_analyzer": "english_stemmed_text",
                    "fields": {
                        "folded": {
                            "type": "text",
                            "analyzer": "folding_text",
                        },
                        "keyword": {
                            "type": "keyword",
                            "normalizer": "lowercase_normalizer",
                        }
                    },
                },
                "comments": {
                    "type": "text",
                    "analyzer": "english_stemmed_text",
                    "search_analyzer": "english_stemmed_text",
                    "fields": {
                        "folded": {
                            "type": "text",
                            "analyzer": "folding_text",
                        },
                    },
                },
                "local_name": {"type": "keyword"},
                "domain": {"type": "keyword"},
                "range": {"type": "keyword"},
                "domain_label": {
                    "type": "text",
                    "analyzer": "english_stemmed_text",
                    "search_analyzer": "english_stemmed_text",
                    "fields": {
                        "folded": {
                            "type": "text",
                            "analyzer": "folding_text",
                        },
                    },
                },
                "range_label": {
                    "type": "text",
                    "analyzer": "english_stemmed_text",
                    "search_analyzer": "english_stemmed_text",
                    "fields": {
                        "folded": {
                            "type": "text",
                            "analyzer": "folding_text",
                        },
                    },
                },
            }
        },
    )
    print(f"Initialized indices: {ENTITY_INDEX}, {SCHEMA_INDEX}")


def build_schema_docs() -> dict[str, dict[str, Any]]:
    print(f"Reading ontology file: {ONTOLOGY_FILE}")
    schema_map: dict[str, dict[str, Any]] = {}
    rdf_types: dict[str, set[str]] = defaultdict(set)
    total_size = os.path.getsize(ONTOLOGY_FILE)

    with open(ONTOLOGY_FILE, "rb") as file:
        progress = tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc="Reading ontology",
        )
        for line_no, raw_line in enumerate(file, start=1):
            progress.update(len(raw_line))
            line = raw_line.decode("utf-8")
            try:
                parsed = parse_nt_line(line)
            except ValueError as exc:
                print(f"Skipping malformed ontology line {line_no}: {exc}", file=sys.stderr)
                continue
            if not parsed:
                continue

            subject, predicate, obj, is_literal, lang = parsed

            if predicate == RDF_TYPE:
                rdf_types[subject].add(obj)
                continue

            doc = schema_map.setdefault(subject, new_schema_doc(subject))

            if predicate == RDFS_LABEL and is_literal and lang in (None, "en"):
                unique_append(doc["labels"], obj)
            elif predicate == RDFS_COMMENT and is_literal and lang in (None, "en"):
                unique_append(doc["comments"], obj)
            elif predicate == RDFS_DOMAIN and not is_literal:
                doc["domain"] = obj
                doc["domain_label"] = split_words(ontology_local_name(obj))
            elif predicate == RDFS_RANGE and not is_literal:
                doc["range"] = obj
                doc["range_label"] = split_words(ontology_local_name(obj))
        progress.close()

    typed_docs: dict[str, dict[str, Any]] = {}
    for uri, types in rdf_types.items():
        kinds = {SCHEMA_TYPES[t] for t in types if t in SCHEMA_TYPES}
        if not kinds:
            continue

        kind = "class" if "class" in kinds else "property"
        doc = schema_map.setdefault(uri, new_schema_doc(uri))
        doc["kind"] = kind
        typed_docs[uri] = doc

    return typed_docs


def new_schema_doc(uri: str) -> dict[str, Any]:
    label, raw = derive_schema_label(uri)
    return {
        "uri": uri,
        "kind": "",
        "labels": [label] if label else [],
        "comments": [],
        "local_name": raw,
        "domain": "",
        "range": "",
        "domain_label": "",
        "range_label": "",
    }


def stream_schema_docs() -> Iterator[dict[str, Any]]:
    for uri, doc in build_schema_docs().items():
        yield {
            "_index": SCHEMA_INDEX,
            "_id": uri,
            "_source": doc,
        }


def stream_entity_docs() -> Iterator[dict[str, Any]]:
    print(f"Streaming instance file: {INSTANCE_FILE}")
    current_uri: str | None = None
    current_doc: dict[str, Any] | None = None
    total_size = os.path.getsize(INSTANCE_FILE)

    def flush() -> dict[str, Any] | None:
        if not current_uri or not current_doc:
            return None
        return {
            "_index": ENTITY_INDEX,
            "_id": current_uri,
            "_source": current_doc,
        }

    with open(INSTANCE_FILE, "rb") as file:
        progress = tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc="Reading instances",
        )
        for line_no, raw_line in enumerate(file, start=1):
            progress.update(len(raw_line))
            line = raw_line.decode("utf-8")
            try:
                parsed = parse_nt_line(line)
            except ValueError as exc:
                print(f"Skipping malformed instance line {line_no}: {exc}", file=sys.stderr)
                continue
            if not parsed:
                continue

            subject, predicate, obj, is_literal, _lang = parsed
            if predicate != RDF_TYPE or is_literal:
                continue

            if current_uri != subject:
                action = flush()
                if action:
                    yield action

                label, raw = derive_entity_label(subject)
                current_uri = subject
                current_doc = {
                    "uri": subject,
                    "label": label,
                    "raw_local_name": raw,
                    "types": [],
                    "type_labels": [],
                }

            assert current_doc is not None
            unique_append(current_doc["types"], obj)
            unique_append(current_doc["type_labels"], split_words(ontology_local_name(obj)))
        progress.close()

    action = flush()
    if action:
        yield action


def bulk_index(actions: Iterator[dict[str, Any]], chunk_size: int) -> int:
    success, errors = helpers.bulk(
        es,
        actions,
        chunk_size=chunk_size,
        request_timeout=120,
        stats_only=True,
        raise_on_error=False,
    )
    if errors:
        print(f"Bulk indexing completed with {errors} failed actions.", file=sys.stderr)
    return success


def finish_index(index: str) -> None:
    es.indices.put_settings(index=index, settings={"refresh_interval": "1s"})
    es.indices.refresh(index=index)


def main() -> int:
    if not os.path.exists(INSTANCE_FILE):
        print(f"Missing instance file: {INSTANCE_FILE}", file=sys.stderr)
        return 1
    if not os.path.exists(ONTOLOGY_FILE):
        print(f"Missing ontology file: {ONTOLOGY_FILE}", file=sys.stderr)
        return 1

    init_indices()

    schema_count = bulk_index(stream_schema_docs(), chunk_size=1000)
    finish_index(SCHEMA_INDEX)
    print(f"Indexed {schema_count} schema documents.")

    entity_count = bulk_index(stream_entity_docs(), chunk_size=5000)
    finish_index(ENTITY_INDEX)
    print(f"Indexed {entity_count} entity documents.")

    print("Index build completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
