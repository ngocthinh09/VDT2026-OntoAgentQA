type JsonBlockProps = {
  value: unknown;
  label?: string;
};

function stringify(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function JsonBlock({ value, label }: JsonBlockProps) {
  return (
    <div className="overflow-hidden rounded-[6px] border border-[var(--line)] bg-[#f7fbfa]">
      {label ? (
        <div className="border-b border-[var(--line)] px-3 py-2 font-data text-[11px] uppercase tracking-[0.16em] text-[var(--muted)]">
          {label}
        </div>
      ) : null}
      <pre className="font-data max-h-72 overflow-auto whitespace-pre-wrap break-words px-3 py-3 text-xs leading-5 text-[var(--graphite)]">
        {stringify(value)}
      </pre>
    </div>
  );
}
