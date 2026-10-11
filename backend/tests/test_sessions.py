import json
import logging

import pytest
from llama_index.core.llms import ChatMessage, MessageRole

from app.agent import sessions as sessions_module
from app.agent.sessions import InMemorySessionStore
from app.observability import JsonFormatter, RequestIdFilter, request_id_var


def turn(i: int) -> list[ChatMessage]:
    return [ChatMessage(role=MessageRole.USER, content=f"q{i}"),
            ChatMessage(role=MessageRole.ASSISTANT, content=f"a{i}")]  # fmt: skip


@pytest.fixture
def clock(monkeypatch):
    """A controllable time.monotonic for TTL tests (no sleeping in tests)."""
    now = [1000.0]
    monkeypatch.setattr(sessions_module.time, "monotonic", lambda: now[0])
    return now


async def test_unknown_session_starts_empty():
    assert await InMemorySessionStore(60, 10).load("new") == []


async def test_sessions_are_isolated_and_load_returns_a_copy():
    store = InMemorySessionStore(60, 10)
    await store.save("alice", turn(1))

    loaded = await store.load("alice")
    loaded.append(ChatMessage(role=MessageRole.USER, content="mutation"))

    assert len(await store.load("alice")) == 2
    assert await store.load("bob") == []


async def test_only_the_last_turns_are_kept():
    store = InMemorySessionStore(60, 10, max_turns=2)
    await store.save("s", turn(1) + turn(2) + turn(3))
    assert [m.content for m in await store.load("s")] == ["q2", "a2", "q3", "a3"]


async def test_sessions_expire_after_ttl(clock):
    store = InMemorySessionStore(ttl_s=60, max_sessions=10)
    await store.save("s", turn(1))

    clock[0] += 59
    assert await store.load("s")
    clock[0] += 2
    assert await store.load("s") == []
    assert len(store) == 0


async def test_least_recently_used_session_is_evicted():
    store = InMemorySessionStore(60, max_sessions=2)
    await store.save("a", turn(1))
    await store.save("b", turn(1))
    await store.load("a")  # "a" is now more recent than "b"
    await store.save("c", turn(1))

    assert await store.load("b") == []
    assert await store.load("a") and await store.load("c")


async def test_delete_and_per_session_locks():
    store = InMemorySessionStore(60, 10)
    await store.save("s", turn(1))
    assert store.lock("s") is store.lock("s")
    assert store.lock("s") is not store.lock("other")

    await store.delete("s")
    assert await store.load("s") == []


def test_json_logs_carry_request_id_and_extra_fields():
    record = logging.makeLogRecord(
        {"name": "app.test", "levelname": "INFO", "msg": "turn %s", "args": ("done",),
         "event": "agent_turn", "cost_usd": 0.0012, "tools": ["query_database"]}
    )  # fmt: skip
    token = request_id_var.set("req-42")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    entry = json.loads(JsonFormatter().format(record))

    assert entry["msg"] == "turn done"
    assert entry["request_id"] == "req-42"
    assert entry["event"] == "agent_turn" and entry["cost_usd"] == 0.0012
    assert entry["tools"] == ["query_database"]
    assert "args" not in entry and "msecs" not in entry
