"""The agent service: runs one conversational turn and streams typed events.

Flow of a turn:
    history + question
      → FunctionAgent (fresh per request: system prompt has today's date, tools share a
        TurnRecorder so citations are numbered across the whole answer)
      → LlamaIndex workflow events (AgentStream / ToolCall / ToolCallResult)
      → our AgentEvents (token / tool_call / tool_result / done / error)  → SSE → browser
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import openai
from llama_index.core.agent.workflow import AgentStream, FunctionAgent, ToolCall, ToolCallResult
from llama_index.core.llms import LLM, ChatMessage, MessageRole
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import WorkflowRuntimeError, WorkflowTimeoutError

from app.agent.events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    TextTrace,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    Usage,
)
from app.agent.prompts import render_system_prompt
from app.agent.recorder import TurnRecorder
from app.agent.tools.database import SCHEMA_DESCRIPTION, OperationalDB
from app.agent.tools.documents import DocumentIndex, SearchResult
from app.agent.tools.pricing import make_quote_fn
from app.config import Settings
from app.data.seed import ensure_fresh
from app.domain.facts import Facts

log = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """Filled in by `OpsAgent.stream`; the caller persists `history` when `ok`."""

    ok: bool = False
    history: list[ChatMessage] = field(default_factory=list)


class OpsAgent:
    def __init__(
        self,
        settings: Settings,
        facts: Facts,
        llm: LLM,
        documents: DocumentIndex,
        db: OperationalDB,
    ):
        self.settings = settings
        self.facts = facts
        self.llm = llm
        self.documents = documents
        self.db = db
        self._tz = ZoneInfo(facts["company"]["timezone"])
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_check = 0.0

    # ---------- tools ----------

    def _tools(self, recorder: TurnRecorder) -> list[FunctionTool]:
        def search_documents(query: str) -> SearchResult:
            """Search HPL's policy documents and contracts (carrier agreement, warehouse SOP,
            customer SLA, hazmat policy, packaging guide, claims & returns).

            Returns numbered passages; cite them inline as [n].

            Args:
                query: A focused natural-language search query, e.g. 'late arrival grace period'.
            """
            hits = self.documents.search(query)
            return SearchResult(
                query, [recorder.cite(h) for h in hits], [h.node.get_content() for h in hits]
            )

        def query_database(sql: str) -> Any:
            """Run ONE read-only SQLite SELECT query against HPL's operational database
            (schema in the system prompt) and return the rows.

            Args:
                sql: A single SELECT statement (SQLite dialect). Use explicit date literals.
            """
            return self.db.run(sql)

        return [
            FunctionTool.from_defaults(fn=search_documents),
            FunctionTool.from_defaults(fn=query_database),
            FunctionTool.from_defaults(fn=make_quote_fn(self.facts)),
        ]

    def _build_agent(self, recorder: TurnRecorder) -> FunctionAgent:
        now = datetime.now(self._tz)
        system_prompt = (
            render_system_prompt(self.facts, now) + "\n\n## Database schema\n" + SCHEMA_DESCRIPTION
        )
        return FunctionAgent(
            name="ops_officer",
            description="Answers logistics operations questions for Harbor & Pine Logistics.",
            tools=self._tools(recorder),
            llm=self.llm,
            system_prompt=system_prompt,
            timeout=self.settings.agent_timeout_s,
        )

    # ---------- data freshness ----------

    async def ensure_fresh_data(self) -> None:
        """Reseeds once a day (all demo dates are relative to 'today')."""
        if time.monotonic() - self._last_refresh_check < self.settings.data_refresh_check_s:
            return
        async with self._refresh_lock:
            if time.monotonic() - self._last_refresh_check < self.settings.data_refresh_check_s:
                return
            rebuilt = await asyncio.to_thread(ensure_fresh, self.settings.db_path, self.facts)
            if rebuilt:
                log.info("Operational database reseeded for a new day")
            self._last_refresh_check = time.monotonic()

    # ---------- a turn ----------

    async def stream(
        self, history: list[ChatMessage], message: str, result: TurnResult
    ) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        recorder = TurnRecorder()
        usage = Usage()
        tool_started: dict[str, float] = {}
        tools_used: list[str] = []

        agent = self._build_agent(recorder)
        # A copy: the buffer appends this turn's tool calls and raw outputs to the list it is
        # given, and only the compact transcript (question + answer) may reach the session.
        memory = ChatMemoryBuffer.from_defaults(
            chat_history=list(history), token_limit=self.settings.history_token_limit, llm=self.llm
        )
        handler = agent.run(
            user_msg=message, memory=memory, max_iterations=self.settings.agent_max_iterations
        )

        try:
            async for ev in handler.stream_events():
                if isinstance(ev, AgentStream):
                    self._add_usage(usage, ev.raw)
                    if ev.delta:
                        yield TokenEvent(delta=ev.delta)
                elif isinstance(ev, ToolCallResult):
                    raw = ev.tool_output.raw_output
                    ok = not ev.tool_output.is_error and not getattr(raw, "error", None)
                    data = (
                        raw.to_ui() if hasattr(raw, "to_ui") else TextTrace(output=str(raw)[:2000])
                    )
                    elapsed = time.perf_counter() - tool_started.pop(
                        ev.tool_id, time.perf_counter()
                    )
                    yield ToolResultEvent(
                        id=ev.tool_id,
                        tool=ev.tool_name,
                        ok=ok,
                        duration_ms=int(elapsed * 1000),
                        data=data,
                    )
                elif isinstance(ev, ToolCall):
                    tool_started[ev.tool_id] = time.perf_counter()
                    tools_used.append(ev.tool_name)
                    yield ToolCallEvent(id=ev.tool_id, tool=ev.tool_name, args=ev.tool_kwargs)

            output = await handler
            answer = (output.response.content or "").strip()
            self._add_cost(usage)
            result.ok = True
            result.history = [
                *history,
                ChatMessage(role=MessageRole.USER, content=message),
                ChatMessage(role=MessageRole.ASSISTANT, content=answer),
            ]
            latency_ms = int((time.perf_counter() - started) * 1000)
            log.info(
                "Turn done: tools=%s tokens=%d+%d cost=%s latency=%d ms",
                ",".join(tools_used) or "-",
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cost_usd,
                latency_ms,
                extra={
                    "event": "agent_turn",
                    "tools": tools_used,
                    "citations": len(recorder.citations),
                    **usage.model_dump(),
                    "latency_ms": latency_ms,
                },
            )
            yield DoneEvent(
                answer=answer, citations=recorder.citations, usage=usage, latency_ms=latency_ms
            )
        except Exception as e:
            code, msg = self._classify_error(e)
            log.exception(
                "Agent turn failed (%s)",
                code,
                extra={"event": "agent_turn_failed", "code": code, "tools": tools_used},
            )
            yield ErrorEvent(code=code, message=msg)
        finally:
            # Client disconnected or we failed mid-run: stop the workflow so it doesn't
            # keep spending tokens in the background.
            if not handler.is_done():
                await handler.cancel_run()

    # ---------- helpers ----------

    @staticmethod
    def _add_usage(usage: Usage, raw: Any) -> None:
        """Token usage arrives once per LLM call, on the stream's final event.

        FunctionAgent hands us the raw provider event as a dict (pydantic model_dump).
        """
        if not isinstance(raw, dict):
            return
        if raw.get("type") == "response.completed":  # Responses API
            stats = (raw.get("response") or {}).get("usage") or {}
            usage.prompt_tokens += stats.get("input_tokens", 0)
            usage.completion_tokens += stats.get("output_tokens", 0)
            usage.llm_calls += 1
        elif raw.get("usage"):  # Chat Completions with stream_options.include_usage
            usage.prompt_tokens += raw["usage"].get("prompt_tokens", 0)
            usage.completion_tokens += raw["usage"].get("completion_tokens", 0)
            usage.llm_calls += 1

    def _add_cost(self, usage: Usage) -> None:
        price_in = self.settings.llm_price_input_per_mtok
        price_out = self.settings.llm_price_output_per_mtok
        if price_in is not None and price_out is not None:
            usage.cost_usd = round(
                (usage.prompt_tokens * price_in + usage.completion_tokens * price_out) / 1e6, 5
            )

    @staticmethod
    def _classify_error(e: Exception) -> tuple[str, str]:
        if isinstance(e, openai.AuthenticationError):
            return "llm_auth", "The AI service rejected the API key. Check OPENAI_API_KEY."
        if isinstance(e, openai.RateLimitError):
            return "llm_rate_limit", "The AI service is busy right now. Please retry shortly."
        if isinstance(e, openai.APITimeoutError | WorkflowTimeoutError | asyncio.TimeoutError):
            return "timeout", "The request took too long. Try a narrower question."
        if isinstance(e, openai.APIConnectionError):
            return "llm_unreachable", "Could not reach the AI service. Check your connection."
        if isinstance(e, WorkflowRuntimeError) and "max iterations" in str(e).lower():
            return "too_many_steps", "The question needed too many steps. Try splitting it up."
        return "internal", "Something went wrong while answering. Please try again."
