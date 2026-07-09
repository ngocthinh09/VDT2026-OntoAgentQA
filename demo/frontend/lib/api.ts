import type { ChatResponse } from "@/lib/types";

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
