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
```
