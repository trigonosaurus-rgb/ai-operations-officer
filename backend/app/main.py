"""FastAPI application.

Run (from backend/):  uv run uvicorn app.main:app --reload
API docs:             http://localhost:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.agent.llm import LLMConfigError, build_llm
from app.agent.service import OpsAgent
from app.agent.sessions import InMemorySessionStore
from app.agent.tools.database import OperationalDB
from app.agent.tools.documents import DocumentIndex
from app.api.routes import router
from app.config import get_settings
from app.data.seed import ensure_fresh
from app.domain.facts import get_facts
from app.observability import RequestIdMiddleware, configure_logging

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: everything expensive happens once here, not per request."""
    settings, facts = get_settings(), get_facts()
    await asyncio.to_thread(ensure_fresh, settings.db_path, facts)
    documents = await asyncio.to_thread(DocumentIndex.load_or_build, settings)
    db = OperationalDB(settings.db_path, settings.sql_row_limit)

    app.state.db = db
    app.state.documents = documents
    app.state.sessions = InMemorySessionStore(
        settings.session_ttl_s, settings.max_sessions, settings.history_max_turns
    )
    # Without an API key the app still starts: data and documents are browsable and
    # /api/chat answers 503 with a clear message instead of the server crashing.
    try:
        app.state.agent = OpsAgent(settings, facts, build_llm(settings), documents, db)
        app.state.agent_error = None
    except LLMConfigError as e:
        log.warning("Agent disabled: %s", e)
        app.state.agent, app.state.agent_error = None, str(e)

    log.info("Ready: model=%s, %d document chunks", settings.llm_model, len(documents.nodes))
    yield


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="AI Operations Officer API",
        version="2.0.0",
        description="Logistics operations agent: hybrid RAG over policy documents, "
        "guarded Text-to-SQL over operational data, and deterministic pricing tools.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(router)

    # One error shape for every failure: {"error": {"code": ..., "message": ...}}
    # (Starlette's HTTPException also covers FastAPI's subclass and unmatched routes.)
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        codes = {404: "not_found", 409: "conflict", 429: "rate_limited", 503: "unavailable"}
        return _error(exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"][1:])
        return _error(422, "invalid_request", f"{field}: {first['msg']}")

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return _error(500, "internal", "Internal server error")

    return app


app = create_app()
