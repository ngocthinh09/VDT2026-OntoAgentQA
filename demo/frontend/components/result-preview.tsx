import type { TracePreview } from "@/lib/trace-format";

type ResultPreviewProps = {
  preview: TracePreview;
};

function metricToneClass(tone: string | undefined) {
  if (tone === "success") {
    return "border-[rgb(14_152_136_/_0.25)] bg-[rgb(14_152_136_/_0.09)] text-[var(--rdf)]";
  }
  if (tone === "danger") {
    return "border-[rgb(184_74_69_/_0.25)] bg-[rgb(184_74_69_/_0.09)] text-[var(--danger)]";
  }
  return "border-[var(--line)] bg-white/80 text-[var(--graphite)]";
}

export function ResultPreview({ preview }: ResultPreviewProps) {
  if (!preview) {
    return null;
  }

  if (preview.kind === "metric") {
    return (
      <div
        className={[
          "rounded-[6px] border px-4 py-3",
          metricToneClass(preview.tone),
        ].join(" ")}
      >
        <div className="font-data text-[10px] uppercase tracking-[0.16em] opacity-70">
          {preview.label}
        </div>
        <div className="mt-1 text-2xl font-semibold">{preview.value}</div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-[6px] border border-[var(--line)] bg-white/90">
      <div className="flex items-center justify-between border-b border-[var(--line)] px-3 py-2">
        <span className="font-data text-[11px] uppercase tracking-[0.16em] text-[var(--muted)]">
          preview
        </span>
        <span className="font-data text-[11px] text-[var(--muted)]">
          {preview.rowCount} row{preview.rowCount === 1 ? "" : "s"}
        </span>
      </div>
      <div className="overflow-auto">
        <table className="w-full min-w-[28rem] border-collapse text-left text-xs">
          <thead className="bg-[#eef7f5] text-[var(--muted)]">
            <tr>
              {preview.columns.map((column) => (
                <th
                  key={column}
                  className="border-b border-[var(--line)] px-3 py-2 font-data font-medium uppercase tracking-[0.12em]"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, rowIndex) => (
              <tr key={`${row.join("-")}-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td
                    key={`${cell}-${cellIndex}`}
                    className="max-w-60 border-b border-[rgb(199_218_215_/_0.7)] px-3 py-2 align-top text-[var(--graphite)]"
                  >
                    <span className="line-clamp-3 break-words">{cell}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview.rowCount > preview.rows.length ? (
        <div className="border-t border-[var(--line)] px-3 py-2 text-xs text-[var(--muted)]">
          Showing {preview.rows.length} of {preview.rowCount} rows. Open raw
          output for the full payload.
        </div>
      ) : null}
    </div>
  );
}
