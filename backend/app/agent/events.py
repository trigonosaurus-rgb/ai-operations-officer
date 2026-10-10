"""Typed events streamed from the agent to the client (one SSE message each).

This is the contract between backend and frontend: the Next.js app renders the
answer, the agent trace and the citations purely from this event sequence:

    tool_call → tool_result → … → token → token → … → done   (or error)
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    """A document passage the agent was given, numbered for inline [n] references."""

    n: int
    slug: str
    doc_id: str
    title: str
    short_title: str
    page: int
    snippet: str
    score: float | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float | None = None


# --- Tool payloads for the trace UI (one shape per tool; the frontend tells them
# apart by their distinctive fields, e.g. `"sql" in data`) ---


class SearchTrace(BaseModel):
    query: str
    citations: list[Citation]


class SqlTrace(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    error: str | None = None


class QuoteLine(BaseModel):
    carrier_code: str
    carrier_name: str
    mode: str
    zone: str
    weight_lb: float
    rate_per_lb: float
    linehaul_usd: float
    fuel_surcharge_usd: float
    hazmat_fee_usd: float
    accessorials_usd: float
    total_usd: float


class QuoteTrace(BaseModel):
    params: dict[str, Any]
    quotes: list[QuoteLine]
    error: str | None = None


class TextTrace(BaseModel):
    """Fallback for tools without a structured payload (or unknown tool names)."""

    output: str


ToolData = SearchTrace | SqlTrace | QuoteTrace | TextTrace


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
    data: ToolData


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


# Discriminated by `type`: pydantic and the generated TypeScript both narrow on it.
AgentEvent = Annotated[
    ToolCallEvent | ToolResultEvent | TokenEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]
