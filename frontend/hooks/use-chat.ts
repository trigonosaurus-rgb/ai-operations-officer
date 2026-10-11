"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ChatError, streamChat } from "@/lib/api/chat-stream";
import { type ChatState, chatReducer, reviveState } from "@/lib/chat/state";

const STORAGE_KEY = "ops-officer:chat:v1";

/** Hex id. crypto.randomUUID() needs HTTPS (or localhost); getRandomValues works everywhere. */
export function randomId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// Reads localStorage, so the component using this hook must only render on the
// client (see useIsClient); otherwise server and client HTML would differ.
function loadState(): ChatState {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return reviveState(JSON.parse(saved) as ChatState);
  } catch {
    // Private mode / corrupted value: start fresh.
  }
  return { sessionId: randomId(), messages: [] };
}

export function useChat() {
  const [state, dispatch] = useReducer(chatReducer, undefined, loadState);
  const abortRef = useRef<AbortController | null>(null);

  const last = state.messages.at(-1);
  const isStreaming = last?.role === "assistant" && last.status === "streaming";

  // Persist once an answer settles: no localStorage write per streamed token.
  useEffect(() => {
    if (isStreaming) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Storage full or unavailable: the chat still works, it just won't survive a reload.
    }
  }, [state, isStreaming]);

  // Leaving the page cancels the request, which also stops the agent on the server.
  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || abortRef.current) return;
      const controller = new AbortController();
      abortRef.current = controller;
      dispatch({ type: "send", content, userId: randomId(), assistantId: randomId() });

      let settled = false;
      try {
        const events = streamChat({ session_id: state.sessionId, message: content }, controller.signal);
        for await (const event of events) {
          dispatch({ type: "event", event });
          if (event.type === "done" || event.type === "error") settled = true;
        }
        if (!settled) {
          dispatch({
            type: "fail",
            code: "disconnected",
            message: "The connection dropped before the answer finished.",
          });
        }
      } catch (err) {
        if (controller.signal.aborted) dispatch({ type: "stop" });
        else if (err instanceof ChatError) dispatch({ type: "fail", code: err.code, message: err.message });
        else dispatch({ type: "fail", code: "client", message: "Something went wrong while reading the answer." });
      } finally {
        abortRef.current = null;
      }
    },
    [state.sessionId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const retry = useCallback(() => {
    const question = state.messages.findLast((m) => m.role === "user");
    if (!question || abortRef.current) return;
    dispatch({ type: "retry" });
    void send(question.content);
  }, [state.messages, send]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    // Forget the server-side memory too; fire-and-forget, the new id isolates us anyway.
    void fetch(`/api/sessions/${state.sessionId}`, { method: "DELETE" }).catch(() => {});
    dispatch({ type: "reset", sessionId: randomId() });
  }, [state.sessionId]);

  return { messages: state.messages, isStreaming, send, stop, retry, reset };
}
