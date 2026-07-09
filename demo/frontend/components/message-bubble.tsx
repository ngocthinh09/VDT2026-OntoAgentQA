import type { ChatMessage } from "@/lib/types";

type MessageBubbleProps = {
  message: ChatMessage;
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <article
        className={[
          "max-w-[88%] rounded-[6px] border px-4 py-3 text-sm leading-6 shadow-sm",
          isUser
            ? "border-[var(--blueprint)] bg-[var(--blueprint)] text-white"
            : "border-[var(--line)] bg-white/90 text-[var(--graphite)]",
        ].join(" ")}
      >
        <div
          className={[
            "font-data mb-1 text-[10px] uppercase tracking-[0.18em]",
            isUser ? "text-white/72" : "text-[var(--rdf)]",
          ].join(" ")}
        >
          {isUser ? "question" : "answer"}
        </div>
        <p className="whitespace-pre-wrap">{message.content}</p>
      </article>
    </div>
  );
}
