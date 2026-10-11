"use client";

// Views that need backend metadata (examples, data overview, health).
// They receive a *promise* from the Server Component and unwrap it with use():
// the page shell renders immediately and these stream in when the data arrives.
import {
  AlertTriangleIcon,
  ArrowRightIcon,
  CalculatorIcon,
  DatabaseIcon,
  type LucideIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  WarehouseIcon,
} from "lucide-react";
import Link from "next/link";
import { use } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import type { ChatMeta } from "@/lib/api/types";
import { formatDate } from "@/lib/format";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  Operations: WarehouseIcon,
  Policy: ScrollTextIcon,
  Pricing: CalculatorIcon,
  "Audit & SLA": ShieldCheckIcon,
};

type AskProps = { meta: Promise<ChatMeta>; onAsk: (q: string) => void; disabled?: boolean };

/** Shown when the backend can't be reached or the agent is disabled (no API key). */
export function BackendNotice({ meta }: { meta: Promise<ChatMeta> }) {
  const { health } = use(meta);
  if (health.ok && health.data.status === "ok") return null;
  const message = health.ok
    ? "The agent is disabled: the backend has no OPENAI_API_KEY. Documents and data are still browsable."
    : `${health.error} Start it with: cd backend && uv run uvicorn app.main:app --port 8000`;
  return (
    <div className="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
      <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
      <span>{message}</span>
    </div>
  );
}

/** Sidebar: all example questions, grouped by the skill they exercise. */
export function ExampleList({ meta, onAsk, disabled }: AskProps) {
  const { examples } = use(meta);
  if (!examples.ok) return null;
  return (
    <div className="space-y-5">
      <p className="px-2 pt-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Try asking</p>
      {examples.data.map((group) => {
        const Icon = CATEGORY_ICONS[group.category] ?? ScrollTextIcon;
        return (
          <section key={group.category}>
            <h3 className="mb-1.5 flex items-center gap-1.5 px-2 text-xs font-medium text-muted-foreground">
              <Icon className="size-3.5" /> {group.category}
            </h3>
            <ul>
              {group.questions.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onAsk(q)}
                    className="w-full rounded-md px-2 py-1.5 text-left text-sm leading-snug transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** Empty state: one starter question per category. */
export function Suggestions({ meta, onAsk, disabled }: AskProps) {
  const { examples } = use(meta);
  if (!examples.ok) return null;
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {examples.data.map((group) => {
        const Icon = CATEGORY_ICONS[group.category] ?? ScrollTextIcon;
        const question = group.questions[0];
        return (
          <button
            key={group.category}
            type="button"
            disabled={disabled}
            onClick={() => onAsk(question)}
            className="group flex flex-col gap-1 rounded-xl border bg-background p-3 text-left text-sm transition-colors hover:border-brand/50 hover:bg-brand-soft/40 disabled:pointer-events-none disabled:opacity-50"
          >
            <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Icon className="size-3.5" /> {group.category}
            </span>
            <span className="leading-snug">{question}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Sidebar footer: what the agent works with. */
export function DataSourcesCard({ meta }: { meta: Promise<ChatMeta> }) {
  const { overview, health } = use(meta);
  if (!overview.ok) return null;
  const docs = health.ok ? health.data.documents : null;
  return (
    <Link
      href="/data"
      className="group block rounded-xl border bg-background p-3 text-sm transition-colors hover:border-brand/50"
    >
      <div className="flex items-center gap-1.5 font-medium">
        <DatabaseIcon className="size-4 text-brand" /> Data sources
        <ArrowRightIcon className="ml-auto size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
      </div>
      <p className="mt-1 text-muted-foreground">{overview.data.company}</p>
      <p className="text-xs text-muted-foreground">
        {docs != null && `${docs} policy documents · `}
        {overview.data.tables.length} tables
        {overview.data.data_as_of && ` · as of ${formatDate(overview.data.data_as_of)}`}
      </p>
      {health.ok && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className={`size-1.5 rounded-full ${health.data.status === "ok" ? "bg-emerald-500" : "bg-destructive"}`} />
          {health.data.model}
        </p>
      )}
    </Link>
  );
}

export function ListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 px-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-4" style={{ width: `${60 + ((i * 37) % 35)}%` }} />
      ))}
    </div>
  );
}
