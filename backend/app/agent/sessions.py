"""Per-session conversation memory.

`SessionStore` is a Protocol (an interface): the API only depends on these four
methods, so the in-memory implementation can later be swapped for Redis without
touching the agent or the routes.

We store a compact transcript (user questions + final answers), not raw tool
outputs: follow-up questions keep their context, while SQL dumps from earlier
turns don't bloat every future prompt.
"""

import asyncio
import time
from collections import OrderedDict
from typing import Protocol

from llama_index.core.llms import ChatMessage


class SessionStore(Protocol):
    async def load(self, session_id: str) -> list[ChatMessage]: ...
    async def save(self, session_id: str, messages: list[ChatMessage]) -> None: ...
    async def delete(self, session_id: str) -> None: ...
    def lock(self, session_id: str) -> asyncio.Lock: ...


class InMemorySessionStore:
    """LRU + TTL dictionary. Fine for one process; use Redis when scaling out."""

    def __init__(self, ttl_s: int, max_sessions: int, max_turns: int = 10):
        self.ttl_s = ttl_s
        self.max_sessions = max_sessions
        self.max_turns = max_turns
        self._data: OrderedDict[str, tuple[float, list[ChatMessage]]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    def _purge_expired(self) -> None:
        now = time.monotonic()
        for sid in [sid for sid, (exp, _) in self._data.items() if exp < now]:
            self._drop(sid)

    def _drop(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        lock = self._locks.get(session_id)
        if lock is not None and not lock.locked():
            del self._locks[session_id]

    async def load(self, session_id: str) -> list[ChatMessage]:
        self._purge_expired()
        entry = self._data.get(session_id)
        if entry is None:
            return []
        self._data.move_to_end(session_id)
        return list(entry[1])

    async def save(self, session_id: str, messages: list[ChatMessage]) -> None:
        self._data[session_id] = (time.monotonic() + self.ttl_s, messages[-2 * self.max_turns :])
        self._data.move_to_end(session_id)
        while len(self._data) > self.max_sessions:
            self._drop(next(iter(self._data)))

    async def delete(self, session_id: str) -> None:
        self._drop(session_id)

    def lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def __len__(self) -> int:
        return len(self._data)
