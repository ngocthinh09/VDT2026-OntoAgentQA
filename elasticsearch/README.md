# Elasticsearch Setup

This project uses Elasticsearch as the retrieval layer for the agent's search tools:

- `search_entity_by_label`
- `search_property_by_label`
- `search_class_by_label`

The indices are built from DBpedia/OntologyQA RDF files and are used by `agents/search_tools.py`.

## Start Elasticsearch

The root `docker-compose.yml` contains a single-node Elasticsearch service.
Start it from the project root:

```bash
docker compose up -d elasticsearch
```

Check that Elasticsearch is running:

```bash
curl http://localhost:9200
```

The default URL used by the project is:

```dotenv
ELASTICSEARCH_URL=http://localhost:9200
```

## Required Data Files

Download the data files from the project release:

```text
https://github.com/ngocthinh09/VDT2026-OntoAgentQA/releases/tag/data-v1
```

The Elasticsearch index builder uses these files by default:

```text
data/instance-types.ttl
data/ontology--DEV_type=parsed_sorted.nt
```

The release may provide compressed files such as:

```text
instance-types.ttl.gz
ontology--DEV_type_parsed_sorted.nt
```

GraphDB can import `.gz` files directly, but `utils/build_index.py` reads plain
text RDF files. If you downloaded `instance-types.ttl.gz`, decompress it before
building the Elasticsearch indices:

```bash
gzip -dk data/instance-types.ttl.gz
```

If your ontology file uses the release name `ontology--DEV_type_parsed_sorted.nt`, either rename it or set `ONTOLOGY_FILE` in `.env`:

```dotenv
ONTOLOGY_FILE=data/ontology--DEV_type_parsed_sorted.nt
```

## Configuration

Relevant `.env` variables:

```dotenv
ELASTICSEARCH_URL=http://localhost:9200
ENTITY_INDEX=entity_index
SCHEMA_INDEX=schema_index

DATA_DIR=data
INSTANCE_FILE=data/instance-types.ttl
ONTOLOGY_FILE=data/ontology--DEV_type=parsed_sorted.nt

OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_EMBEDDING_MODEL=baai/bge-m3
SCHEMA_VECTOR_FIELD=schema_vector
SCHEMA_VECTOR_DIMS=1024
ENABLE_SCHEMA_DENSE=true
EMBEDDING_BATCH_SIZE=64

HYBRID_SEARCH_ENABLED=true
```

`ENABLE_SCHEMA_DENSE=true` generates dense vectors for ontology classes and properties. This improves schema search but requires `OPENROUTER_API_KEY`.

To build only lexical schema search, disable dense embeddings:

```dotenv
ENABLE_SCHEMA_DENSE=false
HYBRID_SEARCH_ENABLED=false
```

## Build Indices

Run the index builder from the project root:

```bash
python utils/build_index.py
```

The script recreates two indices:

```text
entity_index  <- data/instance-types.ttl
schema_index  <- data/ontology--DEV_type=parsed_sorted.nt
```

If you configured custom index names with `ENTITY_INDEX` or `SCHEMA_INDEX`, the script uses those names instead.

## Verify Search Tools

Run the search tools smoke test:

```bash
python utils/test_search_tools.py
```

This checks:

- entity search with `Albert Einstein`
- property search with `birth year`
- class search with `actor`

If the test passes, Elasticsearch retrieval is ready for the agent.

## Optional Browser Search Tool

A small static search helper is available at:

```text
elasticsearch/tools/elasticsearch-search.html
```

You can turn on Live Server in VS Code or open the file directly in a browser. It provides a simple interface to test entity and schema search queries. You must have Elasticsearch running and the indices built to use this tool. It uses `http://localhost:9200`, `entity_index`, and `schema_index` by default, matching the default project configuration.

## Inspect Indices Manually

List indices:

```bash
curl "http://localhost:9200/_cat/indices?v"
```

Search the entity index:

```bash
curl -X GET "http://localhost:9200/entity_index/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{"query":{"multi_match":{"query":"Albert Einstein","fields":["label^4","type_labels"]}},"size":5}'
```

Search the schema index:

```bash
curl -X GET "http://localhost:9200/schema_index/_search?pretty" \
  -H "Content-Type: application/json" \
  -d '{"query":{"bool":{"filter":[{"term":{"kind":"property"}}],"must":{"multi_match":{"query":"birth year","fields":["labels^4","comments","domain_label","range_label"]}}}},"size":5}'
```

## Troubleshooting

- `Elasticsearch search failed`: confirm `docker compose up -d elasticsearch` has completed and `ELASTICSEARCH_URL` is correct.
- `OPENROUTER_API_KEY is required when ENABLE_SCHEMA_DENSE=true`: set `OPENROUTER_API_KEY` or disable dense schema indexing.
- `No such file or directory`: check `INSTANCE_FILE` and `ONTOLOGY_FILE` paths in `.env`.
- Empty search results: rebuild the indices and verify the data files are not empty or still compressed.
