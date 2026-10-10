"""FastAPI dependencies.

Routes never import global singletons; they *ask* for what they need via Depends().
Tests swap any of these with `app.dependency_overrides[get_agent] = lambda: FakeAgent()`.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from app.agent.service import OpsAgent
from app.agent.sessions import SessionStore
from app.agent.tools.database import OperationalDB
from app.agent.tools.documents import DocumentIndex
from app.config import Settings, get_settings


def get_agent(request: Request) -> OpsAgent:
    agent = request.app.state.agent
    if agent is None:
        raise HTTPException(503, detail=request.app.state.agent_error or "Agent unavailable")
    return agent


def get_sessions(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_db(request: Request) -> OperationalDB:
    return request.app.state.db


def get_documents(request: Request) -> DocumentIndex:
    return request.app.state.documents


SettingsDep = Annotated[Settings, Depends(get_settings)]
AgentDep = Annotated[OpsAgent, Depends(get_agent)]
SessionsDep = Annotated[SessionStore, Depends(get_sessions)]
DbDep = Annotated[OperationalDB, Depends(get_db)]
DocumentsDep = Annotated[DocumentIndex, Depends(get_documents)]


# --- Rate limiting (per client IP, moving window) ---
# In-memory, so per process. Behind a reverse proxy run uvicorn with --proxy-headers
# so request.client.host is the real client IP, not the proxy's.
_limiter = MovingWindowRateLimiter(MemoryStorage())


def rate_limit(request: Request, settings: SettingsDep) -> None:
    if not settings.rate_limit_enabled:
        return
    client = request.client.host if request.client else "unknown"
    if not _limiter.hit(parse(settings.rate_limit), "chat", client):
        raise HTTPException(429, detail=f"Rate limit exceeded ({settings.rate_limit}).")
