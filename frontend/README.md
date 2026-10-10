# Frontend

Next.js (App Router) + TypeScript + Tailwind + shadcn/ui. Chat UI for the agent and a data browser.

```bash
npm install
npm run dev          # http://localhost:3000 (expects the backend on :8000)
```

| Env var       | Default                 | Used for                                               |
| ------------- | ----------------------- | ------------------------------------------------------ |
| `BACKEND_URL` | `http://localhost:8000` | `/api/*` proxy (resolved at **build** time) and Server Component fetches (runtime) |

## API types are generated

The backend's Pydantic models are the source of truth. After changing them:

```bash
cd ../backend && uv run python -m scripts.export_openapi   # → lib/api/openapi.json
cd ../frontend && npm run gen:api                          # → lib/api/schema.d.ts
```

## Layout

```
app/page.tsx              chat page (Server Component; streams metadata to the client)
app/data/page.tsx         documents + table browser (Server Components, state in the URL)
components/chat/          chat UI: messages, agent trace, citations, composer
hooks/use-chat.ts         network + persistence around the chat reducer
lib/chat/state.ts         pure reducer: agent events → UI state
lib/api/chat-stream.ts    POST + SSE parsing → typed AgentEvent stream
lib/api/server.ts         backend reads for Server Components (server-only)
app/healthz/route.ts      liveness probe for the container healthcheck
```

## Docker

`output: "standalone"` makes `next build` emit a self-contained `server.js` with only the
files it needs; the [Dockerfile](Dockerfile) copies just that into a slim Node image.
Because `/api/*` rewrites are fixed at build time, `BACKEND_URL` is a **build arg**
(set in the root `docker-compose.yml`).
