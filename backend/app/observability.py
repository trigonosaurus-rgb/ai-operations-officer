"""Logging setup and per-request IDs.

Every request gets an ID (from the X-Request-ID header or a new one). It lives in a
ContextVar, so every log line written while handling the request carries it — the
way to connect "the user saw an error" with "what happened in the logs".

Two output formats (LOG_FORMAT): `text` for humans in a terminal, `json` for log
collectors (Loki, Datadog, CloudWatch…). In JSON mode the `extra={...}` fields of a log
call become top-level keys, so you can query e.g. `event="agent_turn" and cost_usd > 0.01`.

The middleware is plain ASGI rather than Starlette's BaseHTTPMiddleware: it wraps the
whole response lifecycle, including streamed (SSE) bodies, so log lines emitted while
the agent streams still carry the request ID, and the logged duration covers the stream.
"""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("app.http")

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "request_id"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str, fmt: str = "text") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Third-party libraries are chatty at INFO.
    for noisy in ("httpx", "httpcore", "openai", "bm25s", "huggingface_hub", "fastembed"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        rid = headers.get(b"x-request-id", b"").decode()[:64] or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            log.info(
                "%s %s -> %s (%d ms)",
                scope["method"],
                scope["path"],
                status,
                duration_ms,
                extra={
                    "event": "http_request",
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
