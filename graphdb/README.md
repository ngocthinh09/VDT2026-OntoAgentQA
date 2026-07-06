# GraphDB Setup

This directory contains GraphDB-specific setup files for the OntoAgentQA repository.

```text
graphdb/
|-- README.md
|-- import/
|   `-- README.md
|-- queries/
|   |-- check-resource.sparql
|   |-- check-type.sparql
|   |-- count-triples.sparql
|   `-- health-check.sparql
`-- repositories/
    `-- DBPEDIA-config.ttl
```

The repository configuration file is used to create a GraphDB repository. It is not RDF data and must not be imported into the repository as triples.

## Requirements

- GraphDB installed locally or available on a remote server.
- A valid GraphDB license if your GraphDB edition requires one.
- RDF data files downloaded from the project data release.

Download GraphDB from:

```text
https://www.ontotext.com/products/graphdb/
```

After starting GraphDB, the Workbench is usually available at:

```text
http://localhost:7200
```

## Create A Repository From Config

The sample repository configuration is:

```text
graphdb/repositories/DBPEDIA-config.ttl
```

Create the repository from the GraphDB Workbench:

1. Open GraphDB Workbench.
2. Go to `Setup` -> `Repositories`.
3. Click `Create new repository`.
4. Choose `Create from file`.
5. Select `graphdb/repositories/DBPEDIA-config.ttl`.
6. Create the repository.
7. Connect to the newly created repository.

## SPARQL Endpoint

GraphDB exposes each repository as a SPARQL endpoint:

```text
http://<graphdb-host>:<graphdb-port>/repositories/<repository-id>
```

For a local repository with ID `DBPEDIA`, set:

```dotenv
GRAPHDB_ENDPOINT=http://localhost:7200/repositories/DBPEDIA
GRAPHDB_TIMEOUT=30
```

For a remote GraphDB server, replace `localhost:7200` with the actual host and port.

## Import Data

After the repository is created, import the RDF files into it. See:

```text
graphdb/import/README.md
```

## Verify The Repository

After importing data, open the GraphDB SPARQL editor and run:

- `graphdb/queries/health-check.sparql`
- `graphdb/queries/count-triples.sparql`
- `graphdb/queries/check-resource.sparql`
- `graphdb/queries/check-type.sparql`

You can also test the endpoint with `curl`:

```bash
curl -G "http://localhost:7200/repositories/DBPEDIA" \
  -H "Accept: application/sparql-results+json" \
  --data-urlencode "query=SELECT ?s ?p ?o WHERE { ?s ?p ?o . } LIMIT 10"
```

If this returns SPARQL JSON results, the repository is ready for the Python agent.

## References

- GraphDB: https://www.ontotext.com/products/graphdb/
- GraphDB documentation: https://graphdb.ontotext.com/documentation/
