// Client for POST /api/chat. The browser's EventSource can only GET, so we POST
// with fetch and parse the Server-Sent Events from the response body ourselves:
//
//   bytes ─► TextDecoderStream ─► EventSourceParserStream ─► JSON.parse ─► AgentEvent
import { EventSourceParserStream } from "eventsource-parser/stream";

import type { AgentEvent, ApiErrorBody, ChatRequest } from "./types";

export class ChatError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ChatError";
  }
}

/** Yields agent events as they arrive. Throws ChatError for failures before the stream starts. */
export async function* streamChat(
  request: ChatRequest,
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  let res: Response;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new ChatError("network", "Can't reach the server. Check your connection.");
  }

  if (!res.ok || !res.body) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    if (body?.error) throw new ChatError(body.error.code, body.error.message);
    // No JSON error body: the Next.js proxy couldn't reach the backend at all.
    throw new ChatError("unreachable", `The backend is not responding (HTTP ${res.status}).`);
  }

  const reader = res.body
    .pipeThrough(new TextDecoderStream())
    .pipeThrough(new EventSourceParserStream())
    .getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      yield JSON.parse(value.data) as AgentEvent;
    }
  } finally {
    // Runs on normal end, on error, and when the consumer stops early (Stop button).
    reader.cancel().catch(() => {});
  }
}
