// Chat state as a pure reducer: (state, action) => new state.
// No React, no network: every UI change caused by the stream is a plain function
// of the events, which makes it predictable and unit-testable.
import type { AgentEvent, Citation, ToolResultEvent, Usage } from "@/lib/api/types";

export type ToolStep = {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  durationMs?: number;
  data?: ToolResultEvent["data"];
};

export type UserMessage = { id: string; role: "user"; content: string };

export type AssistantMessage = {
  id: string;
  role: "assistant";
  content: string;
  steps: ToolStep[];
  citations: Citation[];
  status: "streaming" | "done" | "error" | "stopped";
  usage?: Usage;
  latencyMs?: number;
  error?: { code: string; message: string };
};

export type Message = UserMessage | AssistantMessage;

export type ChatState = { sessionId: string; messages: Message[] };

export type ChatAction =
  | { type: "send"; content: string; userId: string; assistantId: string }
  | { type: "event"; event: AgentEvent }
  | { type: "fail"; code: string; message: string }
  | { type: "stop" }
  | { type: "retry" }
  | { type: "reset"; sessionId: string };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send":
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: action.userId, role: "user", content: action.content },
          {
            id: action.assistantId,
            role: "assistant",
            content: "",
            steps: [],
            citations: [],
            status: "streaming",
          },
        ],
      };
    case "event":
      return updateLastAssistant(state, (msg) => applyEvent(msg, action.event));
    case "fail":
      return updateLastAssistant(state, (msg) =>
        msg.status === "streaming"
          ? { ...msg, status: "error", error: { code: action.code, message: action.message } }
          : msg,
      );
    case "stop":
      return updateLastAssistant(state, (msg) =>
        msg.status === "streaming" ? { ...msg, status: "stopped" } : msg,
      );
    case "retry":
      // Drop the failed exchange; the caller re-sends the question.
      return { ...state, messages: state.messages.slice(0, -2) };
    case "reset":
      return { sessionId: action.sessionId, messages: [] };
  }
}

function applyEvent(msg: AssistantMessage, event: AgentEvent): AssistantMessage {
  switch (event.type) {
    case "tool_call":
      return {
        ...msg,
        steps: [...msg.steps, { id: event.id, tool: event.tool, args: event.args, status: "running" }],
      };
    case "tool_result": {
      const result = {
        status: event.ok ? "ok" : "error",
        durationMs: event.duration_ms,
        data: event.data,
      } as const;
      const known = msg.steps.some((s) => s.id === event.id);
      return {
        ...msg,
        steps: known
          ? msg.steps.map((s) => (s.id === event.id ? { ...s, ...result } : s))
          : [...msg.steps, { id: event.id, tool: event.tool, args: {}, ...result }],
        // Passages are numbered as soon as they're retrieved, so inline [n] references
        // become clickable while the answer is still streaming.
        citations: "citations" in event.data ? mergeCitations(msg.citations, event.data.citations) : msg.citations,
      };
    }
    case "token":
      return { ...msg, content: msg.content + event.delta };
    case "done":
      return {
        ...msg,
        content: event.answer || msg.content,
        citations: event.citations,
        usage: event.usage,
        latencyMs: event.latency_ms,
        status: "done",
      };
    case "error":
      return { ...msg, status: "error", error: { code: event.code, message: event.message } };
  }
}

function mergeCitations(existing: Citation[], incoming: Citation[]): Citation[] {
  const seen = new Set(existing.map((c) => c.n));
  return [...existing, ...incoming.filter((c) => !seen.has(c.n))];
}

function updateLastAssistant(
  state: ChatState,
  update: (msg: AssistantMessage) => AssistantMessage,
): ChatState {
  const last = state.messages.at(-1);
  if (last?.role !== "assistant") return state;
  return { ...state, messages: [...state.messages.slice(0, -1), update(last)] };
}

/** Restores a saved chat; an answer that was mid-stream when the page closed counts as stopped. */
export function reviveState(saved: ChatState): ChatState {
  return {
    ...saved,
    messages: saved.messages.map((m) =>
      m.role === "assistant" && m.status === "streaming" ? { ...m, status: "stopped" } : m,
    ),
  };
}
