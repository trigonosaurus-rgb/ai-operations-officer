"""Typed events streamed from the agent to the client (one SSE message each).

This is the contract between backend and frontend: the Next.js app renders the
answer, the agent trace and the citations purely from this event sequence:

    tool_call → tool_result → … → token → token → … → done   (or error)
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """A document passage the agent was given, numbered for inline [n] references."""

    n: int
    slug: str
    doc_id: str
    title: str
    page: int
    snippet: str
    score: float | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float | None = None


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    tool: str
    args: dict[str, Any]


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    id: str
    tool: str
    ok: bool
    duration_ms: int
    # Tool-specific structured payload for the trace UI (SQL + rows, citations, quotes…)
    data: dict[str, Any] = Field(default_factory=dict)


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    delta: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    answer: str
    citations: list[Citation]
    usage: Usage
    latency_ms: int


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


AgentEvent = ToolCallEvent | ToolResultEvent | TokenEvent | DoneEvent | ErrorEvent
