import type { ChatResponse } from "@/lib/types";
import { JsonBlock } from "@/components/json-block";
import { TraceStepCard } from "@/components/trace-step-card";

type TracePanelProps = {
  response: ChatResponse | null;
  isLoading: boolean;
};

function formatMs(value?: number) {
  if (typeof value !== "number") {
    return "-";
  }
  if (value < 1000) {
    return `${value} ms`;
  }
  return `${(value / 1000).toFixed(1)} s`;
}

export function TracePanel({ response, isLoading }: TracePanelProps) {
  return (
    <aside className="workbench-panel flex min-h-[34rem] flex-col rounded-[6px]">
      <div className="border-b border-[var(--line)] px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-data text-xs uppercase tracking-[0.2em] text-[var(--blueprint)]">
              Trace
            </p>
            <h2 className="font-display mt-1 text-xl font-semibold">
              Evidence path
            </h2>
          </div>
          {isLoading ? (
            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-[var(--line)]">
              <div className="trace-pulse h-full w-full origin-left bg-[var(--rdf)]" />
            </div>
          ) : null}
        </div>

        <div className="mt-4 grid grid-cols-3 overflow-hidden rounded-[6px] border border-[var(--line)] bg-white/70 text-center">
          <div className="border-r border-[var(--line)] px-3 py-2">
            <div className="font-data text-[11px] text-[var(--muted)]">
              steps
            </div>
            <div className="mt-1 text-lg font-semibold">
              {response?.trace.length ?? 0}
            </div>
          </div>
          <div className="border-r border-[var(--line)] px-3 py-2">
            <div className="font-data text-[11px] text-[var(--muted)]">
              events
            </div>
            <div className="mt-1 text-lg font-semibold">
              {response?.metadata.event_count ?? 0}
            </div>
          </div>
          <div className="px-3 py-2">
            <div className="font-data text-[11px] text-[var(--muted)]">
              time
            </div>
            <div className="mt-1 text-lg font-semibold">
              {formatMs(response?.metadata.elapsed_ms)}
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 space-y-5 overflow-auto px-5 py-5">
        {!response ? (
          <div className="rounded-[6px] border border-dashed border-[var(--line-strong)] bg-white/55 px-4 py-8 text-center text-sm leading-6 text-[var(--muted)]">
            Run a question to see search, inspection, and execution steps.
          </div>
        ) : null}

        {response?.metadata.finalization_error ? (
          <div className="rounded-[6px] border border-[rgb(184_74_69_/_0.24)] bg-[rgb(184_74_69_/_0.08)] px-4 py-3 text-sm text-[var(--danger)]">
            {response.metadata.finalization_error}
          </div>
        ) : null}

        {response?.trace.length ? (
          <div className="trace-rail space-y-4">
            {response.trace.map((step) => (
              <TraceStepCard key={`${step.step}-${step.tool}`} step={step} />
            ))}
          </div>
        ) : null}

        {response?.sparql ? (
          <JsonBlock label="final sparql" value={response.sparql} />
        ) : null}

        {response ? (
          <JsonBlock label="raw result" value={response.raw_result ?? null} />
        ) : null}
      </div>
    </aside>
  );
}
