// Liveness probe for the container healthcheck: answers when the Next.js server is up,
// without touching the backend (the backend has its own healthcheck).
export function GET() {
  return Response.json({ status: "ok" });
}
