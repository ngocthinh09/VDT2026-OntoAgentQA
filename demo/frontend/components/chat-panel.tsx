"use client";

import { FormEvent, KeyboardEvent, useMemo, useState } from "react";
import { MessageBubble } from "@/components/message-bubble";
import { TracePanel } from "@/components/trace-panel";
import { streamQuestion } from "@/lib/api";
import type { ChatMessage, ChatResponse, ChatStreamEvent } from "@/lib/types";

const SAMPLE_QUESTIONS = [
  "Có mấy tàu có cảng đăng ký tại Cam Ranh?",
  "Ai là đạo diễn của bộ phim Titanic?",
  "Albert Einstein sinh ra ở đâu?",
];

function makeId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function emptyStreamingResponse(): ChatResponse {
  return {
    answer: "",
    trace: [],
    sparql: null,
    raw_result: null,
    metadata: {
      elapsed_ms: 0,
      event_count: 0,
      finalization_error: null,
    },
  };
}

export function ChatPanel() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [latestResponse, setLatestResponse] = useState<ChatResponse | null>(
    null,
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSend = question.trim().length > 0 && !isLoading;

  const statusText = useMemo(() => {
    if (isLoading) {
      return "Running agent";
    }
    if (latestResponse) {
      return "Ready";
    }
    return "Waiting for a question";
  }, [isLoading, latestResponse]);

  async function ask(text: string) {
    const cleanQuestion = text.trim();
    if (!cleanQuestion || isLoading) {
      return;
    }

    setQuestion("");
    setError(null);
    setIsLoading(true);
    setMessages((current) => [
      ...current,
      {
        id: makeId(),
        role: "user",
        content: cleanQuestion,
      },
    ]);

    setLatestResponse(emptyStreamingResponse());

    function handleStreamEvent(event: ChatStreamEvent) {
      if (event.event === "trace_step") {
        setLatestResponse((current) => {
          const base = current ?? emptyStreamingResponse();
          return {
            ...base,
            trace: [...base.trace, event.step],
            metadata: {
              ...base.metadata,
              event_count: base.metadata.event_count + 1,
            },
          };
        });
        return;
      }

      if (event.event === "final_answer") {
        setLatestResponse((current) => ({
          answer: event.answer,
          trace: current?.trace ?? [],
          sparql: event.sparql ?? null,
          raw_result: event.raw_result ?? null,
          metadata: event.metadata,
        }));
        setMessages((current) => [
          ...current,
          {
            id: makeId(),
            role: "assistant",
            content: event.answer,
          },
        ]);
        return;
      }

      if (event.event === "error") {
        setError(event.message);
      }
    }

    try {
      await streamQuestion(cleanQuestion, {
        onEvent: handleStreamEvent,
      });
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Could not connect to the demo backend.";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask(question);
    }
  }

  return (
    <section className="grid flex-1 gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(390px,0.85fr)]">
      <div className="workbench-panel flex min-h-[34rem] flex-col rounded-[6px]">
        <div className="flex items-start justify-between gap-4 border-b border-[var(--line)] px-5 py-4">
          <div>
            <p className="font-data text-xs uppercase tracking-[0.2em] text-[var(--rdf)]">
              Chat
            </p>
            <h2 className="font-display mt-1 text-xl font-semibold">
              Natural-language query
            </h2>
          </div>
          <div className="rounded-full border border-[var(--line)] bg-white/70 px-3 py-1 font-data text-xs text-[var(--muted)]">
            {statusText}
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-auto px-5 py-5">
          {messages.length === 0 ? (
            <div className="rounded-[6px] border border-dashed border-[var(--line-strong)] bg-white/55 px-5 py-7">
              <p className="font-display text-lg font-semibold">
                Start with a benchmark-style question.
              </p>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                The backend will return the final answer and a trace of the
                tools used by the agent.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {SAMPLE_QUESTIONS.map((sample) => (
                  <button
                    key={sample}
                    type="button"
                    disabled={isLoading}
                    onClick={() => void ask(sample)}
                    className="rounded-full border border-[var(--line)] bg-white px-3 py-2 text-left text-xs leading-5 text-[var(--graphite)] transition hover:border-[var(--rdf)] hover:text-[var(--rdf)] focus:outline-none focus:ring-2 focus:ring-[var(--rdf)] focus:ring-offset-2"
                  >
                    {sample}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}

          {isLoading ? (
            <div className="flex justify-start">
              <div className="max-w-[88%] rounded-[6px] border border-[var(--line)] bg-white/90 px-4 py-3 shadow-sm">
                <div className="font-data mb-2 text-[10px] uppercase tracking-[0.18em] text-[var(--rdf)]">
                  answer
                </div>
                <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <span className="h-2 w-2 rounded-full bg-[var(--rdf)]" />
                  Agent is streaming trace...
                </div>
              </div>
            </div>
          ) : null}

          {error ? (
            <div className="rounded-[6px] border border-[rgb(184_74_69_/_0.24)] bg-[rgb(184_74_69_/_0.08)] px-4 py-3 text-sm leading-6 text-[var(--danger)]">
              {error}
            </div>
          ) : null}
        </div>

        <form
          onSubmit={handleSubmit}
          className="border-t border-[var(--line)] bg-white/50 px-5 py-4"
        >
          <label
            htmlFor="question"
            className="font-data text-xs uppercase tracking-[0.18em] text-[var(--muted)]"
          >
            Ask a question
          </label>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={handleKeyDown}
              rows={3}
              placeholder="Nhập câu hỏi tiếng Việt..."
              className="min-h-24 flex-1 resize-none rounded-[6px] border border-[var(--line)] bg-white px-4 py-3 text-sm leading-6 text-[var(--graphite)] outline-none transition placeholder:text-[var(--line-strong)] focus:border-[var(--rdf)] focus:ring-2 focus:ring-[rgb(14_152_136_/_0.16)]"
            />
            <button
              type="submit"
              disabled={!canSend}
              className="rounded-[6px] bg-[var(--graphite)] px-5 py-3 font-data text-xs uppercase tracking-[0.18em] text-white transition hover:bg-[var(--rdf)] focus:outline-none focus:ring-2 focus:ring-[var(--rdf)] focus:ring-offset-2 disabled:bg-[var(--line-strong)] sm:w-32"
            >
              Send
            </button>
          </div>
        </form>
      </div>

      <TracePanel response={latestResponse} isLoading={isLoading} />
    </section>
  );
}
