// Friendly names for the generated API types.
// schema.d.ts is generated from the backend's OpenAPI spec (`npm run gen:api`):
// never edit it by hand, change the Pydantic models instead.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ChatRequest = Schemas["ChatRequest"];
export type HealthResponse = Schemas["HealthResponse"];
export type ExampleGroup = Schemas["ExampleGroup"];
export type DocumentInfo = Schemas["DocumentInfo"];
export type DataOverview = Schemas["DataOverview"];
export type TableInfo = Schemas["TableInfo"];
export type TablePreview = Schemas["TablePreview"];

export type Citation = Schemas["Citation"];
export type Usage = Schemas["Usage"];
export type SearchTrace = Schemas["SearchTrace"];
export type SqlTrace = Schemas["SqlTrace"];
export type QuoteTrace = Schemas["QuoteTrace"];
export type QuoteLine = Schemas["QuoteLine"];
export type TextTrace = Schemas["TextTrace"];

export type ToolCallEvent = Schemas["ToolCallEvent"];
export type ToolResultEvent = Schemas["ToolResultEvent"];
export type TokenEvent = Schemas["TokenEvent"];
export type DoneEvent = Schemas["DoneEvent"];
export type ErrorEvent = Schemas["ErrorEvent"];

/** One SSE message from POST /api/chat; narrow it with `switch (event.type)`. */
export type AgentEvent = ToolCallEvent | ToolResultEvent | TokenEvent | DoneEvent | ErrorEvent;

/** Every non-2xx JSON response from the backend has this shape (see backend/app/main.py). */
export type ApiErrorBody = { error: { code: string; message: string } };

/** Server-side reads never throw: pages render a "backend unavailable" state instead. */
export type Result<T> = { ok: true; data: T } | { ok: false; error: string };

/** What the chat page's sidebar and empty state need (see getChatMeta in server.ts). */
export type ChatMeta = {
  health: Result<HealthResponse>;
  examples: Result<ExampleGroup[]>;
  overview: Result<DataOverview>;
};
