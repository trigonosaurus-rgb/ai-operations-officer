// Backend reads for Server Components. `server-only` makes importing this file
// from a Client Component a build error, so BACKEND_URL never ships to the browser.
import "server-only";

import { connection } from "next/server";

import type {
  ApiErrorBody,
  ChatMeta,
  DataOverview,
  DocumentInfo,
  ExampleGroup,
  HealthResponse,
  Result,
  TablePreview,
} from "./types";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

async function get<T>(path: string): Promise<Result<T>> {
  // Request-time data: stops prerendering here, so `next build` never calls the backend.
  await connection();
  try {
    const res = await fetch(`${BACKEND_URL}${path}`, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
      return { ok: false, error: body?.error.message ?? `Backend responded with HTTP ${res.status}.` };
    }
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, error: "The backend is unreachable." };
  }
}

export const getHealth = () => get<HealthResponse>("/api/health");
export const getExamples = () => get<ExampleGroup[]>("/api/examples");
export const getDocuments = () => get<DocumentInfo[]>("/api/documents");
export const getDataOverview = () => get<DataOverview>("/api/data/overview");
export const getTablePreview = (name: string, offset = 0, limit = 50) =>
  get<TablePreview>(
    `/api/data/tables/${encodeURIComponent(name)}?limit=${limit}&offset=${offset}`,
  );

/** Everything the chat page's sidebar and empty state need, fetched in parallel. */
export async function getChatMeta(): Promise<ChatMeta> {
  const [health, examples, overview] = await Promise.all([
    getHealth(),
    getExamples(),
    getDataOverview(),
  ]);
  return { health, examples, overview };
}
