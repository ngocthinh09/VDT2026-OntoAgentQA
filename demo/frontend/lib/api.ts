import type { ChatResponse, ChatStreamEvent } from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

type ErrorPayload = {
  detail?: string;
  message?: string;
};

export async function sendQuestion(
  question: string,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as ErrorPayload;
      message = payload.detail || payload.message || message;
    } catch {
      // Keep the status-based message when the backend does not return JSON.
    }
    throw new Error(message);
  }

  return response.json() as Promise<ChatResponse>;
}

type StreamHandlers = {
  onEvent: (event: ChatStreamEvent) => void;
};

function parseErrorMessage(response: Response) {
  return `Request failed with status ${response.status}`;
}

export async function streamQuestion(
  question: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson",
    },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!response.ok) {
    let message = parseErrorMessage(response);
    try {
      const payload = (await response.json()) as ErrorPayload;
      message = payload.detail || payload.message || message;
    } catch {
      // Keep the status-based message when the backend does not return JSON.
    }
    throw new Error(message);
  }

  if (!response.body) {
    throw new Error("Streaming response body is not available.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function dispatchLine(line: string) {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }
    handlers.onEvent(JSON.parse(trimmed) as ChatStreamEvent);
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      dispatchLine(line);
    }
  }

  buffer += decoder.decode();
  dispatchLine(buffer);
}
