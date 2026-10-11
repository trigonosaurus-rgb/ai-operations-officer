// The reducer is a pure function, so the whole streaming UI logic is testable with
// plain objects: feed it a sequence of server events and check the resulting state.
import { describe, expect, it } from "vitest";

import type { AgentEvent, Citation } from "@/lib/api/types";

import { type AssistantMessage, type ChatAction, type ChatState, chatReducer, reviveState } from "./state";

const citation = (n: number, page = n): Citation => ({
  n,
  slug: "warehouse-operations-sop",
  doc_id: "HPL-OPS-002",
  title: "Warehouse Operations SOP",
  short_title: "Warehouse SOP",
  page,
  snippet: `passage ${n}`,
  score: null,
});

const usage = { prompt_tokens: 1200, completion_tokens: 80, llm_calls: 2, cost_usd: 0.0002 };

const empty: ChatState = { sessionId: "s1", messages: [] };
const send: ChatAction = { type: "send", content: "Can I book a dock?", userId: "u1", assistantId: "a1" };

function run(...events: AgentEvent[]): ChatState {
  return events.reduce<ChatState>(
    (state, event) => chatReducer(state, { type: "event", event }),
    chatReducer(empty, send),
  );
}

function assistant(state: ChatState): AssistantMessage {
  const last = state.messages.at(-1);
  if (last?.role !== "assistant") throw new Error("last message is not from the assistant");
  return last;
}

describe("chatReducer", () => {
  it("adds the question and an empty streaming answer on send", () => {
    const state = chatReducer(empty, send);
    expect(state.messages).toEqual([
      { id: "u1", role: "user", content: "Can I book a dock?" },
      { id: "a1", role: "assistant", content: "", steps: [], citations: [], status: "streaming" },
    ]);
  });

  it("builds the agent trace from tool_call and tool_result", () => {
    const sql = { sql: "SELECT 1", columns: ["1"], rows: [[1]], row_count: 1, truncated: false, error: null };
    const state = run(
      { type: "tool_call", id: "t1", tool: "query_database", args: { sql: "SELECT 1" } },
      { type: "tool_result", id: "t1", tool: "query_database", ok: true, duration_ms: 12, data: sql },
    );
    expect(assistant(state).steps).toEqual([
      { id: "t1", tool: "query_database", args: { sql: "SELECT 1" }, status: "ok", durationMs: 12, data: sql },
    ]);
  });

  it("shows a running step until its result arrives, and marks failed tools", () => {
    const running = run({ type: "tool_call", id: "t1", tool: "query_database", args: {} });
    expect(assistant(running).steps[0].status).toBe("running");

    const failed = chatReducer(running, {
      type: "event",
      event: { type: "tool_result", id: "t1", tool: "query_database", ok: false, duration_ms: 3, data: { output: "Rejected" } },
    });
    expect(assistant(failed).steps[0].status).toBe("error");
  });

  it("keeps a result whose call event was missed", () => {
    const state = run({ type: "tool_result", id: "t9", tool: "quote_shipment", ok: true, duration_ms: 1, data: { output: "ok" } });
    expect(assistant(state).steps).toMatchObject([{ id: "t9", tool: "quote_shipment", args: {}, status: "ok" }]);
  });

  it("makes citations available while the answer is still streaming, without duplicates", () => {
    const state = run(
      { type: "tool_result", id: "t1", tool: "search_documents", ok: true, duration_ms: 5,
        data: { query: "a", citations: [citation(1), citation(2)] } },
      { type: "tool_result", id: "t2", tool: "search_documents", ok: true, duration_ms: 5,
        data: { query: "b", citations: [citation(2), citation(3)] } },
      { type: "token", delta: "See [3]" },
    );
    expect(assistant(state).citations.map((c) => c.n)).toEqual([1, 2, 3]);
    expect(assistant(state).status).toBe("streaming");
  });

  it("appends tokens, then lets done set the final answer and metadata", () => {
    const state = run(
      { type: "token", delta: "Yes, " },
      { type: "token", delta: "dock 3." },
      { type: "done", answer: "Yes, dock 3 at 09:00.", citations: [citation(1)], usage, latency_ms: 2100 },
    );
    expect(assistant(state)).toMatchObject({
      content: "Yes, dock 3 at 09:00.",
      status: "done",
      usage,
      latencyMs: 2100,
      citations: [citation(1)],
    });
  });

  it("keeps the streamed text if done carries an empty answer", () => {
    const state = run({ type: "token", delta: "partial" }, { type: "done", answer: "", citations: [], usage, latency_ms: 1 });
    expect(assistant(state).content).toBe("partial");
  });

  it("records server-side errors", () => {
    const state = run({ type: "error", code: "llm_rate_limit", message: "busy" });
    expect(assistant(state)).toMatchObject({ status: "error", error: { code: "llm_rate_limit", message: "busy" } });
  });

  it("fail and stop only affect an answer that is still streaming", () => {
    const done = run({ type: "done", answer: "ok", citations: [], usage, latency_ms: 1 });
    expect(chatReducer(done, { type: "fail", code: "network", message: "x" })).toEqual(done);
    expect(chatReducer(done, { type: "stop" })).toEqual(done);

    const streaming = chatReducer(empty, send);
    expect(assistant(chatReducer(streaming, { type: "stop" })).status).toBe("stopped");
    expect(assistant(chatReducer(streaming, { type: "fail", code: "network", message: "offline" }))).toMatchObject({
      status: "error",
      error: { code: "network", message: "offline" },
    });
  });

  it("ignores events when there is no assistant message to update", () => {
    expect(chatReducer(empty, { type: "event", event: { type: "token", delta: "x" } })).toBe(empty);
  });

  it("retry drops the failed exchange; reset starts a new session", () => {
    const failed = run({ type: "error", code: "internal", message: "x" });
    expect(chatReducer(failed, { type: "retry" }).messages).toEqual([]);
    expect(chatReducer(failed, { type: "reset", sessionId: "s2" })).toEqual({ sessionId: "s2", messages: [] });
  });

  it("never mutates the previous state", () => {
    const before = chatReducer(empty, send);
    const snapshot = structuredClone(before);
    chatReducer(before, { type: "event", event: { type: "token", delta: "x" } });
    expect(before).toEqual(snapshot);
  });
});

describe("reviveState", () => {
  it("marks an answer interrupted by a page reload as stopped", () => {
    const saved = run({ type: "token", delta: "half an ans" });
    const revived = reviveState(saved);
    expect(assistant(revived).status).toBe("stopped");
    expect(assistant(revived).content).toBe("half an ans");
  });
});
