# Import RDF Data Into GraphDB

This guide explains how to load the RDF data required by the OntoAgentQA system into a GraphDB repository.

## Download Data

Download the RDF data files from the project data release:

```text
https://github.com/ngocthinh09/VDT2026-OntoAgentQA/releases/tag/data-v1
```

Place the files under the project `data/` directory.

Expected release files:

```text
data/ontology--DEV_type_parsed_sorted.nt
data/objects_mapping.ttl.gz
data/literals_mapping.ttl.gz
data/instance-types.ttl.gz
```

GraphDB can import the compressed `.gz` files directly. You do not need to decompress them before importing.

Approximate release asset sizes:

```text
ontology--DEV_type_parsed_sorted.nt  4.69 MB
objects_mapping.ttl.gz               255 MB
literals_mapping.ttl.gz              214 MB
instance-types.ttl.gz                62.8 MB
```

## Recommended Import Order

For normal Workbench import, use this order:

```text
1. data/ontology--DEV_type_parsed_sorted.nt
2. data/objects_mapping.ttl.gz
3. data/literals_mapping.ttl.gz
4. data/instance-types.ttl.gz
```

The final RDF graph should not depend on this order as long as every file is loaded successfully. This order is chosen for practical import time and debugging:

- Load the small ontology/schema file first.
- Then load the largest files first: object mappings, then literal mappings.
- Load `instance-types.ttl.gz` after the larger mapping files.

## Workbench Import Steps

1. Open GraphDB Workbench.
2. Connect to the target repository.
3. Go to `Import`.
4. Choose `Import from file`.
5. Select the RDF file to import.
6. Keep the default import settings.
7. Click `Import`.
8. Wait until the import status is completed.
9. Repeat for the next file.

## Verify Imported Data

After all files are imported, open the GraphDB SPARQL editor and run:

- `graphdb/queries/health-check.sparql`
- `graphdb/queries/count-triples.sparql`
- `graphdb/queries/check-resource.sparql`
- `graphdb/queries/check-type.sparql`

If the two `ASK` queries return `true`, the repository contains the expected DBpedia resources and type assertions.

## Note

- Do not import the repository config file as RDF data. The config file under `graphdb/repositories/` is only used when creating the repository.

## References

- GraphDB data loading documentation: [GraphDB/Loading-and-Updating-Data](https://graphdb.ontotext.com/documentation/10.8/loading-and-updating-data.html)
