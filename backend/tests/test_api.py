"""HTTP contract tests: the real FastAPI app with the agent swapped for a fake.

`TestClient(app)` without a `with` block does not run the lifespan, so no document
index is loaded and no model is downloaded — state is wired by hand instead, and the
agent dependency is replaced through `app.dependency_overrides` (the reason routes get
the agent via Depends() rather than importing a global).
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from llama_index.core.llms import ChatMessage, MessageRole

from app.agent.events import DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent, Usage
from app.agent.sessions import InMemorySessionStore
from app.api import deps
from app.api.deps import get_agent
from app.config import get_settings
from app.main import create_app


class FakeAgent:
    """Echoes the question and records the history each turn received."""

    def __init__(self):
        self.histories: list[list[str]] = []
        self.fail = False

    async def ensure_fresh_data(self) -> None:
        pass

    async def stream(self, history, message, result):
        self.histories.append([m.content for m in history])
        if self.fail:
            yield ErrorEvent(code="internal", message="Something went wrong")
            return
        answer = f"echo: {message}"
        yield ToolCallEvent(id="t1", tool="query_database", args={"sql": "SELECT 1"})
        yield TokenEvent(delta=answer)
        result.ok = True
        result.history = [*history, ChatMessage(role=MessageRole.USER, content=message),
                          ChatMessage(role=MessageRole.ASSISTANT, content=answer)]  # fmt: skip
        yield DoneEvent(answer=answer, citations=[], usage=Usage(), latency_ms=1)


@pytest.fixture
def agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
def app(settings, db, agent):
    app = create_app()
    app.state.db = db
    app.state.documents = SimpleNamespace(nodes=["chunk"] * 3)
    app.state.sessions = InMemorySessionStore(ttl_s=60, max_sessions=100)
    app.state.agent, app.state.agent_error = agent, None
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_agent] = lambda: agent
    deps._limiter.storage.reset()
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def chat(client: TestClient, message: str, session_id: str = "session-0001"):
    return client.post("/api/chat", json={"session_id": session_id, "message": message})


def sse_events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def assert_error(response, status: int, code: str) -> str:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    return body["error"]["message"]


# --- system ---


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["data_as_of"] == "2026-10-07"
    assert (body["documents"], body["document_chunks"]) == (6, 3)


def test_health_is_degraded_without_llm(app, client):
    app.state.agent = None
    assert client.get("/api/health").json()["status"] == "degraded"


def test_request_id_is_echoed_or_generated(client):
    assert (
        client.get("/api/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    assert len(client.get("/api/health").headers["x-request-id"]) == 12


def test_unknown_route_uses_the_common_error_shape(client):
    assert_error(client.get("/api/nope"), 404, "not_found")


# --- chat ---


def test_chat_streams_typed_events(client):
    response = chat(client, "hello")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response)
    assert [e["type"] for e in events] == ["tool_call", "token", "done"]
    assert events[-1]["answer"] == "echo: hello"


def test_memory_is_kept_per_session(client, agent):
    chat(client, "first", "session-a1")
    chat(client, "second", "session-a1")
    chat(client, "other", "session-b1")

    assert agent.histories == [[], ["first", "echo: first"], []]


def test_failed_turn_is_not_remembered(client, agent):
    agent.fail = True
    assert sse_events(chat(client, "boom"))[-1]["type"] == "error"
    agent.fail = False
    chat(client, "again")

    assert agent.histories[-1] == []


def test_deleting_a_session_forgets_it(client, agent):
    chat(client, "remember me")
    assert client.delete("/api/sessions/session-0001").status_code == 204
    chat(client, "who am I?")

    assert agent.histories[-1] == []


def test_concurrent_turn_in_the_same_session_is_refused(app, client):
    asyncio.run(app.state.sessions.lock("session-0001").acquire())  # a turn is in flight

    events = sse_events(chat(client, "hello"))

    assert events == [{"type": "error", "code": "busy", "message": "This chat is still answering."}]


def test_chat_without_api_key_is_503_with_a_clear_message(app, client):
    del app.dependency_overrides[get_agent]
    app.state.agent, app.state.agent_error = None, "OPENAI_API_KEY is not set."

    assert "OPENAI_API_KEY" in assert_error(chat(client, "hi"), 503, "unavailable")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"session_id": "session-0001", "message": ""}, "message"),
        ({"session_id": "session-0001", "message": "x" * 2001}, "message"),
        ({"session_id": "short", "message": "hi"}, "session_id"),
        ({"session_id": "../../etc/passwd", "message": "hi"}, "session_id"),
        ({"message": "hi"}, "session_id"),
    ],
)
def test_invalid_chat_requests_are_rejected(client, body, field):
    message = assert_error(client.post("/api/chat", json=body), 422, "invalid_request")
    assert message.startswith(field)


def test_rate_limit(settings, app, client):
    limited = settings.model_copy(update={"rate_limit_enabled": True, "rate_limit": "2/minute"})
    app.dependency_overrides[get_settings] = lambda: limited

    assert chat(client, "1").status_code == 200
    assert chat(client, "2").status_code == 200
    assert_error(chat(client, "3"), 429, "rate_limited")


# --- documents ---


def test_documents_are_listed_with_download_urls(client):
    docs = client.get("/api/documents").json()
    assert len(docs) == 6
    assert {"slug": "hazmat-policy", "url": "/api/documents/hazmat-policy.pdf"}.items() <= next(
        d for d in docs if d["slug"] == "hazmat-policy"
    ).items()


def test_pdf_is_served_inline(client):
    response = client.get("/api/documents/hazmat-policy.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content.startswith(b"%PDF")


@pytest.mark.parametrize("slug", ["unknown", "..%2F..%2F.env", "..%2Fcompany%2Ffacts"])
def test_only_catalogued_documents_can_be_downloaded(client, slug):
    response = client.get(f"/api/documents/{slug}.pdf")
    assert response.status_code == 404
    assert not response.content.startswith(b"%PDF")


# --- data browser ---


def test_data_overview_lists_every_table(client):
    body = client.get("/api/data/overview").json()
    assert body["company"] == "Harbor & Pine Logistics"
    tables = {t["name"]: t for t in body["tables"]}
    assert len(tables) == 7
    assert tables["carriers"]["row_count"] == 6
    assert "hazmat_certified" in tables["carriers"]["columns"]


def test_table_preview_is_paginated(client):
    first = client.get("/api/data/tables/shipments?limit=5").json()
    second = client.get("/api/data/tables/shipments?limit=5&offset=5").json()
    assert len(first["rows"]) == len(second["rows"]) == 5
    assert first["rows"][0][0] != second["rows"][0][0]
    assert first["row_count"] > 100


@pytest.mark.parametrize("name", ["meta", "sqlite_master", "shipments; DROP TABLE shipments"])
def test_only_whitelisted_tables_are_browsable(client, name):
    assert_error(client.get(f"/api/data/tables/{name}"), 404, "not_found")


def test_page_size_is_bounded(client):
    assert_error(client.get("/api/data/tables/shipments?limit=500"), 422, "invalid_request")
