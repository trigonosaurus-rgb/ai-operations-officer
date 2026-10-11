# syntax=docker/dockerfile:1
# Frontend image (build context: frontend/). Three stages, following the official
# Next.js "with-docker" example: deps → build → a runtime with only the standalone
# server (no node_modules, no source).

ARG NODE_VERSION=24.21.0

# ---------- deps: exactly what package-lock.json says ----------
FROM node:${NODE_VERSION}-trixie-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

# ---------- build ----------
FROM node:${NODE_VERSION}-trixie-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# The /api/* proxy target is resolved at BUILD time (next.config.ts rewrites),
# so it has to arrive as a build arg — a runtime env var would be too late for it.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL} \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---------- runtime ----------
FROM node:${NODE_VERSION}-trixie-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# `output: "standalone"` traces the files the server really needs into .next/standalone,
# including a minimal server.js. Static assets are copied next to it by hand.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/healthz').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]

CMD ["node", "server.js"]
