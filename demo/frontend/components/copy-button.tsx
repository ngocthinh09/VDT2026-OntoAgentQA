"use client";

import { useState } from "react";

type CopyButtonProps = {
  value: string;
  label?: string;
  className?: string;
};

export function CopyButton({
  value,
  label = "Copy",
  className = "",
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    if (!value) {
      return;
    }

    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={[
        "rounded-full border border-[var(--line)] bg-white/85 px-2.5 py-1 font-data text-[10px] uppercase tracking-[0.14em] text-[var(--muted)] transition hover:border-[var(--rdf)] hover:text-[var(--rdf)] focus:outline-none focus:ring-2 focus:ring-[var(--rdf)] focus:ring-offset-2",
        className,
      ].join(" ")}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
