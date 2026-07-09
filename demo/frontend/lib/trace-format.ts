import type { TraceStep } from "@/lib/types";

type JsonRecord = Record<string, unknown>;

export type PreviewTable = {
  kind: "table";
  columns: string[];
  rows: string[][];
  rowCount: number;
};

export type PreviewMetric = {
  kind: "metric";
  label: string;
  value: string;
  tone?: "success" | "danger" | "neutral";
};

export type TracePreview = PreviewTable | PreviewMetric | null;

const SEARCH_COLUMNS = ["label", "uri", "score", "kind", "domain", "range"];
const PROPERTY_EXAMPLE_COLUMNS = [
  "subject_label",
  "subject_uri",
  "property_label",
  "object_label",
  "object",
];

export function stringifyForCopy(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function compact(value: unknown, fallback = "-") {
  if (value === null || value === undefined) {
    return fallback;
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(3);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "string") {
    return value.trim() || fallback;
  }
  return stringifyForCopy(value);
}

function localName(value: unknown) {
  const text = compact(value);
  if (text === "-") {
    return text;
  }
  const clean = text.replace(/^<|>$/g, "");
  const last = clean.split(/[\/#]/).filter(Boolean).at(-1) ?? clean;
  try {
    return decodeURIComponent(last).replaceAll("_", " ");
  } catch {
    return last.replaceAll("_", " ");
  }
}

function inputValue(input: unknown, keys: string[]) {
  if (!isRecord(input)) {
    return compact(input);
  }
  for (const key of keys) {
    if (input[key] !== undefined) {
      return compact(input[key]);
    }
  }
  return stringifyForCopy(input);
}

function searchTable(output: unknown): PreviewTable | null {
  const rows = asArray(output).filter(isRecord);
  if (!rows.length) {
    return null;
  }

  const columns = SEARCH_COLUMNS.filter((column) =>
    rows.some((row) => row[column] !== undefined && row[column] !== ""),
  );

  return {
    kind: "table",
    columns,
    rowCount: rows.length,
    rows: rows.slice(0, 6).map((row) =>
      columns.map((column) => {
        if (column === "uri" || column === "domain" || column === "range") {
          return localName(row[column]);
        }
        return compact(row[column]);
      }),
    ),
  };
}

function bindingValue(value: unknown) {
  if (isRecord(value) && "value" in value) {
    return compact(value.value);
  }
  return compact(value);
}

function bindingTable(output: unknown): PreviewTable | null {
  const rows = asArray(output).filter(isRecord);
  if (!rows.length) {
    return null;
  }

  const columns = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>()),
  );

  if (!columns.length) {
    return null;
  }

  return {
    kind: "table",
    columns,
    rowCount: rows.length,
    rows: rows.slice(0, 8).map((row) =>
      columns.map((column) => bindingValue(row[column])),
    ),
  };
}

function propertyExamplesTable(output: unknown): PreviewTable | null {
  const rows = asArray(output).filter(isRecord);
  if (!rows.length) {
    return null;
  }

  const columns = PROPERTY_EXAMPLE_COLUMNS.filter((column) =>
    rows.some((row) => row[column] !== undefined && row[column] !== ""),
  );

  return {
    kind: "table",
    columns,
    rowCount: rows.length,
    rows: rows.slice(0, 6).map((row) =>
      columns.map((column) => {
        if (column === "subject_uri" || column === "object") {
          return localName(row[column]);
        }
        return compact(row[column]);
      }),
    ),
  };
}

function knowledgeGraphPreview(output: unknown): PreviewTable | null {
  if (!isRecord(output) || !Array.isArray(output.properties)) {
    return null;
  }

  const properties = output.properties.filter(isRecord);
  if (!properties.length) {
    return null;
  }

  return {
    kind: "table",
    columns: ["property", "values"],
    rowCount: properties.length,
    rows: properties.slice(0, 8).map((property) => {
      const values = asArray(property.values)
        .filter(isRecord)
        .slice(0, 3)
        .map((value) => compact(value.value_label ?? value.value))
        .join(", ");
      return [
        compact(property.property_label ?? property.property_uri),
        values || "-",
      ];
    }),
  };
}

function executePreview(output: unknown): TracePreview {
  if (typeof output === "boolean") {
    return {
      kind: "metric",
      label: "ASK result",
      value: output ? "true" : "false",
      tone: output ? "success" : "danger",
    };
  }

  const table = bindingTable(output);
  if (table) {
    return table;
  }

  if (Array.isArray(output)) {
    return {
      kind: "metric",
      label: "SELECT rows",
      value: String(output.length),
      tone: output.length ? "success" : "neutral",
    };
  }

  return null;
}

export function getTracePreview(step: TraceStep): TracePreview {
  if (step.status === "error") {
    return {
      kind: "metric",
      label: "status",
      value: "error",
      tone: "danger",
    };
  }

  if (step.type === "search") {
    return searchTable(step.output);
  }

  if (step.tool === "get_property_examples") {
    return propertyExamplesTable(step.output);
  }

  if (step.tool === "get_knowledgegraph_entry") {
    return knowledgeGraphPreview(step.output);
  }

  if (step.type === "execute") {
    return executePreview(step.output);
  }

  return null;
}

export function getRawResultPreview(rawResult: unknown): TracePreview {
  return executePreview(rawResult);
}

export function summarizeTraceStep(step: TraceStep) {
  if (step.error) {
    return step.error;
  }

  const outputRows = asArray(step.output);
  if (step.type === "search") {
    const query = inputValue(step.input, ["query"]);
    return `Searched ${step.tool?.replaceAll("_", " ") ?? "index"} for "${query}" and found ${outputRows.length} match${outputRows.length === 1 ? "" : "es"}.`;
  }

  if (step.tool === "get_knowledgegraph_entry") {
    const entity = inputValue(step.input, ["entity_uri"]);
    const propertyCount =
      isRecord(step.output) && Array.isArray(step.output.properties)
        ? step.output.properties.length
        : 0;
    return `Inspected "${entity}" and returned ${propertyCount} outgoing propert${propertyCount === 1 ? "y" : "ies"}.`;
  }

  if (step.tool === "get_property_examples") {
    const property = inputValue(step.input, ["property_uri"]);
    return `Loaded ${outputRows.length} example triple${outputRows.length === 1 ? "" : "s"} for "${property}".`;
  }

  if (step.type === "execute") {
    if (typeof step.output === "boolean") {
      return `Executed ASK query and returned ${step.output ? "true" : "false"}.`;
    }
    if (Array.isArray(step.output)) {
      return `Executed SELECT query and returned ${step.output.length} row${step.output.length === 1 ? "" : "s"}.`;
    }
    return "Executed SPARQL query.";
  }

  return step.tool ? `Ran ${step.tool}.` : "Ran tool call.";
}
