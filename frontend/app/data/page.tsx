import { AlertTriangleIcon, ChevronLeftIcon, ChevronRightIcon, ExternalLinkIcon, FileTextIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { DataTable } from "@/components/data-table";
import { SiteHeader } from "@/components/site-header";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getDataOverview, getDocuments, getTablePreview } from "@/lib/api/server";
import { formatDate, formatNumber, pdfUrl } from "@/lib/format";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "Data sources" };

const PAGE_SIZE = 50;

const TABLE_NOTES: Record<string, string> = {
  warehouses: "Facilities, dock counts, hazmat docks and opening hours",
  carriers: "Contracted carriers, modes, zones and hazmat certification",
  customers: "Accounts with service tier and account manager",
  rate_cards: "Contracted $/lb rates per carrier, mode and zone",
  dock_slots: "Dock appointments for the coming weeks",
  shipments: "Outbound shipments: dates, status, exceptions, cost",
  inventory: "Stock on hand, reservations and reorder points",
};

// Server Component: no "use client", no JS shipped for this page's content.
// The selected table lives in the URL (?table=…&page=…), so views are shareable.
export default function DataPage({ searchParams }: PageProps<"/data">) {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main className="mx-auto w-full max-w-6xl space-y-12 px-4 py-8 sm:py-10">
        <header className="max-w-2xl space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Data sources</h1>
          <p className="text-muted-foreground">
            Everything the agent can see. Harbor &amp; Pine Logistics is a fictional company: the
            documents and the database are generated from one fact sheet, and all dates are
            regenerated relative to today so the demo never goes stale.
          </p>
        </header>

        <section className="space-y-4">
          <SectionTitle title="Policy documents" note="Searched with hybrid retrieval (BM25 + embeddings); answers cite the page." />
          <Suspense fallback={<GridSkeleton />}>
            <DocumentGrid />
          </Suspense>
        </section>

        <section className="space-y-4">
          <SectionTitle title="Operational database" note="SQLite, opened read-only for the agent. Every query is checked to be a single SELECT." />
          <Suspense fallback={<Skeleton className="h-96 rounded-xl" />}>
            <TableBrowser searchParams={searchParams} />
          </Suspense>
        </section>
      </main>
    </div>
  );
}

function SectionTitle({ title, note }: { title: string; note: string }) {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="text-sm text-muted-foreground">{note}</p>
    </div>
  );
}

async function DocumentGrid() {
  const docs = await getDocuments();
  if (!docs.ok) return <BackendError message={docs.error} />;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {docs.data.map((doc) => (
        <a
          key={doc.slug}
          href={pdfUrl(doc.slug)}
          target="_blank"
          rel="noreferrer"
          className="group flex flex-col rounded-xl border p-4 transition-colors hover:border-brand/50"
        >
          <div className="flex items-start gap-2">
            <FileTextIcon className="mt-0.5 size-4 shrink-0 text-brand" />
            <div className="min-w-0">
              <p className="font-medium leading-snug">{doc.title}</p>
              <p className="text-xs text-muted-foreground">
                {doc.doc_id} · v{doc.version} · {doc.owner}
              </p>
            </div>
            <ExternalLinkIcon className="ml-auto size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{doc.summary}</p>
          <p className="mt-auto pt-3 text-xs text-muted-foreground">Effective {doc.effective}</p>
        </a>
      ))}
    </div>
  );
}

async function TableBrowser({ searchParams }: { searchParams: PageProps<"/data">["searchParams"] }) {
  const [params, overview] = await Promise.all([searchParams, getDataOverview()]);
  if (!overview.ok) return <BackendError message={overview.error} />;

  const tables = overview.data.tables;
  const requested = typeof params.table === "string" ? params.table : undefined;
  const table = tables.find((t) => t.name === requested) ?? tables.find((t) => t.name === "shipments") ?? tables[0];
  const pageCount = Math.max(1, Math.ceil(table.row_count / PAGE_SIZE));
  const page = Math.min(pageCount, Math.max(1, Number(params.page) || 1));
  const preview = await getTablePreview(table.name, (page - 1) * PAGE_SIZE, PAGE_SIZE);

  const href = (name: string, p = 1) => `/data?table=${name}${p > 1 ? `&page=${p}` : ""}`;

  return (
    <div className="grid gap-4 lg:grid-cols-[15rem_1fr]">
      <nav className="flex gap-1 overflow-x-auto lg:flex-col" aria-label="Tables">
        {tables.map((t) => (
          <Link
            key={t.name}
            href={href(t.name)}
            scroll={false}
            className={cn(
              "shrink-0 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-muted",
              t.name === table.name && "bg-muted font-medium",
            )}
          >
            <span className="font-mono">{t.name}</span>
            <span className="ml-2 text-xs text-muted-foreground tabular-nums">{formatNumber(t.row_count)}</span>
          </Link>
        ))}
      </nav>

      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
          <div>
            <h3 className="font-mono font-semibold">{table.name}</h3>
            <p className="text-sm text-muted-foreground">{TABLE_NOTES[table.name]}</p>
          </div>
          <p className="ml-auto text-xs text-muted-foreground">
            {formatNumber(table.row_count)} rows · {table.columns.length} columns
            {overview.data.data_as_of && ` · generated ${formatDate(overview.data.data_as_of)}`}
          </p>
        </div>

        {preview.ok ? (
          <DataTable columns={preview.data.columns} rows={preview.data.rows} className="max-h-[32rem]" />
        ) : (
          <BackendError message={preview.error} />
        )}

        {pageCount > 1 && (
          <div className="flex items-center justify-end gap-2 text-sm">
            <span className="mr-2 text-muted-foreground tabular-nums">
              Page {page} of {pageCount}
            </span>
            <PagerLink href={href(table.name, page - 1)} disabled={page <= 1} label="Previous page">
              <ChevronLeftIcon />
            </PagerLink>
            <PagerLink href={href(table.name, page + 1)} disabled={page >= pageCount} label="Next page">
              <ChevronRightIcon />
            </PagerLink>
          </div>
        )}
      </div>
    </div>
  );
}

function PagerLink({ href, disabled, label, children }: { href: string; disabled: boolean; label: string; children: React.ReactNode }) {
  const cls = buttonVariants({ variant: "outline", size: "icon-sm" });
  if (disabled) {
    return (
      <span aria-disabled className={cn(cls, "pointer-events-none opacity-40")}>
        {children}
      </span>
    );
  }
  return (
    <Link href={href} scroll={false} aria-label={label} className={cls}>
      {children}
    </Link>
  );
}

function BackendError({ message }: { message: string }) {
  return (
    <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
      <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
      {message}
    </div>
  );
}

function GridSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-40 rounded-xl" />
      ))}
    </div>
  );
}
