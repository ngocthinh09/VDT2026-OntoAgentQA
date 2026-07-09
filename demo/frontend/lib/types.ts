export type TraceStep = {
  step: number;
  type: string;
  tool?: string | null;
  input?: unknown;
  output?: unknown;
  duration_ms?: number | null;
  status: string;
  error?: string | null;
};

export type ChatMetadata = {
  elapsed_ms: number;
  event_count: number;
  finalization_error?: string | null;
};

export type ChatResponse = {
  answer: string;
  trace: TraceStep[];
  sparql?: string | null;
  raw_result?: unknown;
  metadata: ChatMetadata;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type ChatStreamEvent =
  | {
      event: "run_started";
      question: string;
    }
  | {
      event: "trace_step";
      step: TraceStep;
    }
  | {
      event: "final_answer";
      answer: string;
      sparql?: string | null;
      raw_result?: unknown;
      metadata: ChatMetadata;
    }
  | {
      event: "error";
      message: string;
    }
  | {
      event: "done";
    };
