"""Logging setup and per-request IDs.

Every request gets an ID (from the X-Request-ID header or a new one). It lives in a
ContextVar, so every log line written while handling the request carries it — the
way to connect "the user saw an error" with "what happened in the logs".

The middleware is plain ASGI rather than Starlette's BaseHTTPMiddleware: it wraps the
whole response lifecycle, including streamed (SSE) bodies, so log lines emitted while
the agent streams still carry the request ID, and the logged duration covers the stream.
"""

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
log = logging.getLogger("app.http")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
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
            log.info(
                "%s %s -> %s (%d ms)",
                scope["method"],
                scope["path"],
                status,
                (time.perf_counter() - started) * 1000,
            )
            request_id_var.reset(token)
