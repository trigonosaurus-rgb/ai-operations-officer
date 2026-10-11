# syntax=docker/dockerfile:1
# Backend image. Build context is the REPO ROOT (the image needs ../data too):
#   docker build -f backend/Dockerfile .
#
# Two stages: `builder` has uv and build caches, `runtime` gets only the virtualenv,
# the code, the data and the pre-built index. Final layout mirrors the repo, so
# app/config.py resolves data/ and var/ exactly as it does locally:
#   /app/backend  /app/data  /app/var

ARG PYTHON_VERSION=3.12.15

# ---------- builder: dependencies + baked document index ----------
FROM python:${PYTHON_VERSION}-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app/backend

# 1) Dependencies only. This layer is rebuilt when uv.lock/pyproject.toml change,
#    not on every code edit — the slow part of the build stays cached.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# 2) Code and data.
COPY backend/ ./
COPY data/ /app/data/

# 3) Bake the embedding model (~65 MB ONNX) and the vector/BM25 index into the image:
#    the container then starts in seconds and never downloads anything at runtime.
RUN .venv/bin/python -m scripts.build_index


# ---------- runtime: what actually ships ----------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

# Unprivileged user: a compromised process can't modify the code or the image.
RUN useradd --create-home --uid 10001 app

WORKDIR /app/backend

COPY --from=builder /app/backend /app/backend
COPY --from=builder /app/data /app/data
# var/ holds the index (read-only use) and the SQLite DB, which is (re)seeded on
# startup for the current day — so this directory must be writable by `app`.
COPY --from=builder --chown=app:app /app/var /app/var

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# One worker on purpose: chat sessions live in process memory (InMemorySessionStore).
# Scaling out means swapping in a shared store (e.g. Redis) first.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
