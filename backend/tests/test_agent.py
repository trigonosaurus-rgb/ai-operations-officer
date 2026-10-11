"""The real agent loop (LlamaIndex FunctionAgent + our tools + the seeded DB), driven by
a scripted LLM instead of OpenAI.

The LLM is the only non-deterministic part of the system. Replacing it with a script
("first call query_database with this SQL, then answer X") lets us test everything
around it — tool wiring, guard behavior inside the loop, citation numbering, the event
stream, error mapping — deterministically, offline and for free. Whether the *real*
model picks the right tools is a different question, answered by evals/ instead.
"""

import itertools
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
import openai
import pytest
from llama_index.core.base.llms.types import ToolCallBlock
from llama_index.core.llms import ChatMessage, MessageRole, MockFunctionCallingLLM
from llama_index.core.schema import NodeWithScore, TextNode

from app.agent.events import (
    DoneEvent,
    ErrorEvent,
    QuoteTrace,
    SearchTrace,
    SqlTrace,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    Usage,
)
from app.agent.prompts import render_system_prompt
from app.agent.recorder import SNIPPET_CHARS
from app.agent.service import OpsAgent, TurnResult

# A script step is either the final answer (str), tool calls (list of (name, kwargs)),
# or an exception the "LLM" raises.
Step = str | list[tuple[str, dict[str, Any]]] | Exception


def scripted_llm(steps) -> tuple[MockFunctionCallingLLM, list[list[ChatMessage]]]:
    """Returns the LLM and a log of the messages it received on each call."""
    script = iter(steps)
    received: list[list[ChatMessage]] = []

    def respond(messages, **_kwargs) -> ChatMessage:
        received.append(list(messages))
        step = next(script)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, str):
            return ChatMessage(role=MessageRole.ASSISTANT, content=step)
        calls = [
            ToolCallBlock(tool_call_id=f"call_{uuid4().hex[:8]}", tool_name=name, tool_kwargs=kw)
            for name, kw in step
        ]
        return ChatMessage(role=MessageRole.ASSISTANT, blocks=calls)

    return MockFunctionCallingLLM(response_generator=respond), received


class FakeDocuments:
    """Stands in for the vector/BM25 index: no embedding model needed."""

    def __init__(self):
        self.nodes = [
            TextNode(
                id_=f"node-{i}",
                text=f"Passage {i} about dock appointments.",
                metadata={
                    "slug": "warehouse-operations-sop",
                    "doc_id": "HPL-OPS-002",
                    "title": "Warehouse Operations SOP",
                    "short_title": "Warehouse SOP",
                    "page": i + 1,
                },
            )
            for i in range(3)
        ]

    def search(self, query: str) -> list[NodeWithScore]:
        picked = self.nodes[:2] if query == "first" else self.nodes[1:]
        return [NodeWithScore(node=n, score=0.5) for n in picked]


@pytest.fixture
def make_agent(settings, facts, db):
    def make(steps, **overrides) -> tuple[OpsAgent, list[list[ChatMessage]]]:
        llm, received = scripted_llm(steps)
        return OpsAgent(
            settings.model_copy(update=overrides), facts, llm, FakeDocuments(), db
        ), received

    return make


async def run_turn(agent: OpsAgent, message: str = "question", history=None):
    result = TurnResult()
    events = [ev async for ev in agent.stream(history or [], message, result)]
    return events, result


def sql_call(sql: str):
    return [("query_database", {"sql": sql})]


# --- happy path ---


async def test_turn_streams_trace_then_answer(make_agent):
    agent, received = make_agent([
        sql_call("SELECT code FROM carriers WHERE hazmat_certified = 0 ORDER BY code"),
        "CSC, LKX and RDP are not hazmat-certified.",
    ])  # fmt: skip

    events, result = await run_turn(agent, "Which carriers can't take hazmat?")

    kinds = [e.type for e in events]
    assert kinds[:2] == ["tool_call", "tool_result"] and kinds[-1] == "done"
    assert "token" in kinds

    call, res, done = events[0], events[1], events[-1]
    assert isinstance(call, ToolCallEvent) and call.tool == "query_database"
    assert isinstance(res, ToolResultEvent) and res.ok and res.id == call.id
    assert isinstance(res.data, SqlTrace) and res.data.rows == [["CSC"], ["LKX"], ["RDP"]]
    assert (
        isinstance(done, DoneEvent) and done.answer == "CSC, LKX and RDP are not hazmat-certified."
    )
    assert "".join(e.delta for e in events if isinstance(e, TokenEvent)) == done.answer

    # The LLM saw the real query result on its second call.
    tool_msg = received[1][-1]
    assert tool_msg.role == MessageRole.TOOL and "3 row(s)" in tool_msg.content

    assert result.ok
    assert [m.content for m in result.history] == ["Which carriers can't take hazmat?", done.answer]


async def test_history_and_todays_date_reach_the_llm(make_agent):
    agent, received = make_agent(["Sure."])
    history = [ChatMessage(role=MessageRole.USER, content="Earlier question"),
               ChatMessage(role=MessageRole.ASSISTANT, content="Earlier answer")]  # fmt: skip

    _, result = await run_turn(agent, "Follow-up", history)

    first_call = received[0]
    assert first_call[0].role == MessageRole.SYSTEM
    assert "Today is" in first_call[0].content and "## Database schema" in first_call[0].content
    assert [m.content for m in first_call[1:]] == [
        "Earlier question",
        "Earlier answer",
        "Follow-up",
    ]
    assert len(result.history) == 4


# --- tools inside the loop ---


async def test_rejected_sql_is_shown_as_failed_step_and_agent_self_corrects(make_agent):
    agent, received = make_agent([
        sql_call("DELETE FROM shipments"),
        sql_call("SELECT COUNT(*) FROM shipments"),
        "Done.",
    ])  # fmt: skip

    events, result = await run_turn(agent)

    first, second = [e for e in events if isinstance(e, ToolResultEvent)]
    assert not first.ok and first.data.error.startswith("Rejected")
    assert second.ok
    assert "Rejected" in received[1][-1].content  # the LLM was told why
    assert result.ok


async def test_citations_are_numbered_across_searches(make_agent):
    agent, _ = make_agent([
        [("search_documents", {"query": "first"})],
        [("search_documents", {"query": "second"})],
        "Appointments are mandatory [1][3].",
    ])  # fmt: skip

    events, _ = await run_turn(agent)

    searches = [e.data for e in events if isinstance(e, ToolResultEvent)]
    assert all(isinstance(s, SearchTrace) for s in searches)
    assert [c.n for c in searches[0].citations] == [1, 2]
    assert [c.n for c in searches[1].citations] == [2, 3]  # node-1 keeps its number
    done = events[-1]
    assert [(c.n, c.page) for c in done.citations] == [(1, 1), (2, 2), (3, 3)]


async def test_llm_reads_the_full_passage_not_the_ui_snippet(make_agent):
    """Regression: the LLM used to get the 900-char UI preview, which cut off answers
    sitting at the end of a chunk (found by the `carrier-probation` eval case)."""
    agent, received = make_agent([[("search_documents", {"query": "first"})], "ok"])
    agent.documents.nodes[0].set_content("Filler sentence. " * 80 + "10.2 Probation: below 90%.")

    events, _ = await run_turn(agent)

    citation = events[1].data.citations[0]
    assert len(citation.snippet) <= SNIPPET_CHARS and "Probation" not in citation.snippet
    assert "10.2 Probation: below 90%." in received[1][-1].content


async def test_parallel_tool_calls_are_all_traced(make_agent):
    agent, _ = make_agent([
        [("quote_shipment", {"zone": "Z3", "weight_lb": 3200, "liftgate": True}),
         ("search_documents", {"query": "first"})],
        "Cheapest is ...",
    ])  # fmt: skip

    events, _ = await run_turn(agent)

    results = {e.tool: e for e in events if isinstance(e, ToolResultEvent)}
    assert set(results) == {"quote_shipment", "search_documents"}
    assert isinstance(results["quote_shipment"].data, QuoteTrace)
    assert results["quote_shipment"].data.quotes[0].total_usd > 0


# --- failures ---


def _rate_limit_error() -> openai.RateLimitError:
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1"))
    return openai.RateLimitError("rate limited", response=response, body=None)


@pytest.mark.parametrize(
    ("error", "code"),
    [(_rate_limit_error(), "llm_rate_limit"), (RuntimeError("boom"), "internal")],
)
async def test_llm_failure_ends_the_stream_with_an_error_event(make_agent, error, code):
    agent, _ = make_agent([error])

    events, result = await run_turn(agent)

    assert isinstance(events[-1], ErrorEvent) and events[-1].code == code
    assert not result.ok and result.history == []  # a failed turn is not remembered


async def test_endless_tool_loop_is_stopped(make_agent):
    agent, _ = make_agent(itertools.repeat(sql_call("SELECT 1")), agent_max_iterations=3)

    events, result = await run_turn(agent)

    assert isinstance(events[-1], ErrorEvent) and events[-1].code == "too_many_steps"
    assert not result.ok


# --- helpers ---


def test_usage_is_summed_over_llm_calls_and_priced(make_agent):
    agent, _ = make_agent([])
    usage = Usage()
    completed = {"type": "response.completed",
                 "response": {"usage": {"input_tokens": 1000, "output_tokens": 200}}}  # fmt: skip
    for raw in (completed, completed, {"type": "response.output_text.delta"}, None):
        agent._add_usage(usage, raw)
    agent._add_cost(usage)

    assert (usage.prompt_tokens, usage.completion_tokens, usage.llm_calls) == (2000, 400, 2)
    assert usage.cost_usd == pytest.approx((2000 * 0.10 + 400 * 0.50) / 1e6)


def test_system_prompt_resolves_relative_dates(facts):
    prompt = render_system_prompt(facts, datetime(2026, 10, 7, 9, 30))
    assert "Today is Wednesday 2026-10-07. Tomorrow is Thursday 2026-10-08." in prompt
    assert "CHI1 = Chicago Central DC" in prompt
    assert "LKX = Lakeshore Express" in prompt
