"use client";

import {
  CalculatorIcon,
  CheckIcon,
  ChevronRightIcon,
  DatabaseIcon,
  FileSearchIcon,
  Loader2Icon,
  type LucideIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import { useState } from "react";

import { SqlBlock } from "@/components/chat/sql-block";
import { DataTable } from "@/components/data-table";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { QuoteTrace, SearchTrace, SqlTrace } from "@/lib/api/types";
import type { ToolStep } from "@/lib/chat/state";
import { citationLabel, formatMoney, formatMs, pdfUrl } from "@/lib/format";
import { cn } from "@/lib/utils";

type ToolMeta = { label: string; running: string; icon: LucideIcon };

const TOOLS: Record<string, ToolMeta> = {
  search_documents: { label: "Searched documents", running: "Searching documents", icon: FileSearchIcon },
  query_database: { label: "Queried database", running: "Querying the database", icon: DatabaseIcon },
  quote_shipment: { label: "Priced shipment", running: "Pricing the shipment", icon: CalculatorIcon },
};

export function toolMeta(tool: string): ToolMeta {
  return TOOLS[tool] ?? { label: tool, running: `Running ${tool}`, icon: WrenchIcon };
}

/** Collapsible "what the agent did" panel: each tool call with its inputs and results. */
export function AgentTrace({ steps }: { steps: ToolStep[] }) {
  const [open, setOpen] = useState(false);
  if (steps.length === 0) return null;
  const totalMs = steps.reduce((sum, s) => sum + (s.durationMs ?? 0), 0);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border bg-muted/20">
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition-colors hover:bg-muted/50">
        <ChevronRightIcon className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-90")} />
        <span className="font-medium">Agent trace</span>
        <span className="flex items-center gap-1 text-muted-foreground">
          {steps.map((s) => {
            const Icon = toolMeta(s.tool).icon;
            return <Icon key={s.id} className={cn("size-3.5", s.status === "error" && "text-destructive")} />;
          })}
        </span>
        <span className="ml-auto text-muted-foreground tabular-nums">
          {steps.length} {steps.length === 1 ? "step" : "steps"} · {formatMs(totalMs)}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ol className="space-y-4 border-t px-3 py-3">
          {steps.map((step, i) => (
            <TraceStep
              key={step.id}
              step={step}
              retried={step.status === "error" && steps.slice(i + 1).some((s) => s.tool === step.tool)}
            />
          ))}
        </ol>
      </CollapsibleContent>
    </Collapsible>
  );
}

function TraceStep({ step, retried }: { step: ToolStep; retried: boolean }) {
  const meta = toolMeta(step.tool);
  const Icon = meta.icon;

  return (
    <li className="relative pl-8">
      <span className="absolute top-0 left-0 flex size-6 items-center justify-center rounded-full border bg-background">
        <Icon className="size-3.5 text-muted-foreground" />
      </span>
      <div className="flex min-h-6 items-center gap-2 text-sm">
        <span className="font-medium">{step.status === "running" ? meta.running : meta.label}</span>
        <code className="rounded bg-muted px-1 font-mono text-[0.7rem] text-muted-foreground">{step.tool}</code>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground tabular-nums">
          {step.durationMs != null && formatMs(step.durationMs)}
          {step.status === "running" && <Loader2Icon className="size-3.5 animate-spin" />}
          {step.status === "ok" && <CheckIcon className="size-3.5 text-brand" />}
          {step.status === "error" && <XIcon className="size-3.5 text-destructive" />}
        </span>
      </div>
      <div className="mt-2 space-y-2">
        <StepBody step={step} />
        {retried && (
          <p className="text-xs text-muted-foreground">
            ↻ The agent read this error and corrected itself in the next step.
          </p>
        )}
      </div>
    </li>
  );
}

function StepBody({ step }: { step: ToolStep }) {
  const { data, args } = step;
  if (!data) {
    // Still running: show what was asked.
    if (typeof args.sql === "string") return <SqlBlock sql={args.sql} />;
    if (typeof args.query === "string") return <Query text={args.query} />;
    return <Params params={args} />;
  }
  if ("sql" in data) return <SqlResult data={data} />;
  if ("citations" in data) return <SearchResult data={data} />;
  if ("quotes" in data) return <QuoteResult data={data} />;
  return <pre className="max-h-48 overflow-auto rounded-md bg-muted/40 p-2 text-xs whitespace-pre-wrap">{data.output}</pre>;
}

function SqlResult({ data }: { data: SqlTrace }) {
  return (
    <>
      <SqlBlock sql={data.sql} />
      {data.error ? (
        <ErrorNote>{data.error}</ErrorNote>
      ) : data.row_count === 0 ? (
        <p className="text-xs text-muted-foreground">Query returned no rows.</p>
      ) : (
        <>
          <DataTable columns={data.columns} rows={data.rows} dense className="max-h-64" />
          <p className="text-xs text-muted-foreground">
            {data.rows.length < data.row_count || data.truncated
              ? `Showing ${data.rows.length} of ${data.row_count}${data.truncated ? "+" : ""} rows`
              : `${data.row_count} ${data.row_count === 1 ? "row" : "rows"}`}
          </p>
        </>
      )}
    </>
  );
}

function SearchResult({ data }: { data: SearchTrace }) {
  return (
    <>
      <Query text={data.query} />
      {data.citations.length === 0 ? (
        <p className="text-xs text-muted-foreground">No relevant passages found.</p>
      ) : (
        <ul className="space-y-1.5">
          {data.citations.map((c) => (
            <li key={c.n} className="rounded-md border bg-background p-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-brand">[{c.n}]</span>
                <a href={pdfUrl(c.slug, c.page)} target="_blank" rel="noreferrer" className="font-medium hover:underline">
                  {citationLabel(c)}
                </a>
                {c.score != null && (
                  <span className="ml-auto text-muted-foreground tabular-nums" title="Fused retrieval score">
                    {c.score.toFixed(3)}
                  </span>
                )}
              </div>
              <p className="mt-1 line-clamp-2 text-muted-foreground">{c.snippet}</p>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function QuoteResult({ data }: { data: QuoteTrace }) {
  return (
    <>
      <Params params={data.params} />
      {data.error ? (
        <ErrorNote>{data.error}</ErrorNote>
      ) : (
        <DataTable
          dense
          columns={["carrier", "mode", "$/lb", "linehaul", "fuel", "hazmat", "extras", "total"]}
          rows={data.quotes.map((q) => [
            `${q.carrier_name} (${q.carrier_code})`,
            q.mode,
            q.rate_per_lb,
            formatMoney(q.linehaul_usd),
            formatMoney(q.fuel_surcharge_usd),
            formatMoney(q.hazmat_fee_usd),
            formatMoney(q.accessorials_usd),
            formatMoney(q.total_usd),
          ])}
        />
      )}
    </>
  );
}

function Query({ text }: { text: string }) {
  return <p className="text-xs text-muted-foreground">“{text}”</p>;
}

function Params({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params).filter(([, v]) => v !== null && v !== false && v !== "");
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded border bg-background px-1.5 py-0.5 font-mono text-[0.7rem]">
          {v === true ? k : `${k}: ${String(v)}`}
        </span>
      ))}
    </div>
  );
}

function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-destructive/30 bg-destructive/5 px-2 py-1.5 font-mono text-xs text-destructive">
      {children}
    </p>
  );
}
