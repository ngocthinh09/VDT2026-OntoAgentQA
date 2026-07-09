import type { TraceStep } from "@/lib/types";
import { CopyButton } from "@/components/copy-button";
import { JsonBlock } from "@/components/json-block";
import { ResultPreview } from "@/components/result-preview";
import {
  getTracePreview,
  stringifyForCopy,
  summarizeTraceStep,
} from "@/lib/trace-format";

type TraceStepCardProps = {
  step: TraceStep;
};

const toneByType: Record<
  string,
  {
    dot: string;
    badge: string;
    label: string;
  }
> = {
  search: {
    dot: "bg-[var(--rdf)]",
    badge: "border-[rgb(14_152_136_/_0.26)] bg-[rgb(14_152_136_/_0.09)] text-[var(--rdf)]",
    label: "Search",
  },
  inspect: {
    dot: "bg-[var(--blueprint)]",
    badge: "border-[rgb(47_111_159_/_0.26)] bg-[rgb(47_111_159_/_0.09)] text-[var(--blueprint)]",
    label: "Inspect",
  },
  execute: {
    dot: "bg-[var(--query)]",
    badge: "border-[rgb(200_138_19_/_0.28)] bg-[rgb(200_138_19_/_0.12)] text-[var(--query)]",
    label: "Execute",
  },
  tool: {
    dot: "bg-[var(--line-strong)]",
    badge: "border-[var(--line)] bg-white text-[var(--muted)]",
    label: "Tool",
  },
};

function getTone(type: string) {
  return toneByType[type] ?? toneByType.tool;
}

export function TraceStepCard({ step }: TraceStepCardProps) {
  const tone = getTone(step.type);
  const hasError = step.status === "error" || Boolean(step.error);
  const summary = summarizeTraceStep(step);
  const preview = getTracePreview(step);

  return (
    <div className="relative pl-10">
      <div
        className={[
          "absolute left-[13px] top-4 h-3 w-3 rounded-full ring-4 ring-[#f4faf8]",
          hasError ? "bg-[var(--danger)]" : tone.dot,
        ].join(" ")}
      />
      <details
        className="group rounded-[6px] border border-[var(--line)] bg-white/86 shadow-sm"
        open={step.step === 1 || step.type === "execute" || hasError}
      >
        <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-3 marker:hidden">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-data text-xs text-[var(--muted)]">
                Step {step.step}
              </span>
              <span
                className={[
                  "rounded-full border px-2 py-0.5 font-data text-[10px] uppercase tracking-[0.16em]",
                  hasError
                    ? "border-[rgb(184_74_69_/_0.28)] bg-[rgb(184_74_69_/_0.1)] text-[var(--danger)]"
                    : tone.badge,
                ].join(" ")}
              >
                {hasError ? "Error" : tone.label}
              </span>
            </div>
            <h3 className="mt-1 truncate font-data text-sm text-[var(--graphite)]">
              {step.tool ?? "tool call"}
            </h3>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--muted)]">
              {summary}
            </p>
          </div>
          <span className="font-data mt-1 text-xs text-[var(--muted)] transition-transform group-open:rotate-180">
            v
          </span>
        </summary>

        <div className="space-y-4 border-t border-[var(--line)] px-4 py-4">
          {step.error ? (
            <div className="rounded-[6px] border border-[rgb(184_74_69_/_0.24)] bg-[rgb(184_74_69_/_0.08)] px-3 py-2 text-sm text-[var(--danger)]">
              {step.error}
            </div>
          ) : null}

          <ResultPreview preview={preview} />

          <div className="grid gap-3 xl:grid-cols-2">
            <JsonBlock
              label="input"
              value={step.input ?? null}
              maxHeightClassName="max-h-52"
            />
            <JsonBlock
              label="raw output"
              value={step.output ?? null}
              maxHeightClassName="max-h-52"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <CopyButton label="Copy input" value={stringifyForCopy(step.input)} />
            <CopyButton
              label="Copy output"
              value={stringifyForCopy(step.output)}
            />
          </div>
        </div>
      </details>
    </div>
  );
}
