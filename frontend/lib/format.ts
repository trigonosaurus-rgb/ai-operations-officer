import type { Citation } from "@/lib/api/types";

export function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function formatUsd(value: number): string {
  // Per-answer costs are fractions of a cent: show enough digits to be meaningful.
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

export const formatNumber = (n: number) => n.toLocaleString("en-US");

export const formatMoney = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** The PDF viewer built into browsers understands #page=N. */
export const pdfUrl = (slug: string, page?: number) =>
  `/api/documents/${slug}.pdf${page ? `#page=${page}` : ""}`;

export const citationLabel = (c: Pick<Citation, "short_title" | "page">) =>
  `${c.short_title} · p.${c.page}`;
