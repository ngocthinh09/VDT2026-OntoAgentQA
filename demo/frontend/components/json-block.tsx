import { CopyButton } from "@/components/copy-button";
import { stringifyForCopy } from "@/lib/trace-format";

type JsonBlockProps = {
  value: unknown;
  label?: string;
  maxHeightClassName?: string;
};

export function JsonBlock({
  value,
  label,
  maxHeightClassName = "max-h-72",
}: JsonBlockProps) {
  const text = stringifyForCopy(value);

  return (
    <div className="overflow-hidden rounded-[6px] border border-[var(--line)] bg-[#f7fbfa]">
      {label ? (
        <div className="flex items-center justify-between gap-3 border-b border-[var(--line)] px-3 py-2">
          <span className="font-data text-[11px] uppercase tracking-[0.16em] text-[var(--muted)]">
            {label}
          </span>
          <CopyButton value={text} />
        </div>
      ) : null}
      <pre
        className={[
          "font-data overflow-auto whitespace-pre-wrap break-words px-3 py-3 text-xs leading-5 text-[var(--graphite)]",
          maxHeightClassName,
        ].join(" ")}
      >
        {text}
      </pre>
    </div>
  );
}
