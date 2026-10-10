import { FileTextIcon } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Citation } from "@/lib/api/types";
import { citationLabel, pdfUrl } from "@/lib/format";

/** Inline [n] marker in an answer: hover for the passage, click to open the PDF page. */
export function CitationRef({ n, citation }: { n: number; citation?: Citation }) {
  if (!citation) return <sup className="text-muted-foreground">[{n}]</sup>;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <a
            data-cite
            href={pdfUrl(citation.slug, citation.page)}
            target="_blank"
            rel="noreferrer"
            className="mx-0.5 inline-flex h-4 min-w-4 -translate-y-1 items-center justify-center rounded bg-brand/15 px-1 align-baseline text-[0.7rem] font-semibold text-brand no-underline transition-colors hover:bg-brand hover:text-brand-foreground"
          />
        }
      >
        {n}
      </TooltipTrigger>
      <TooltipContent className="block max-w-sm space-y-1 p-3 text-left">
        <p className="font-semibold">{citationLabel(citation)}</p>
        <p className="line-clamp-5 opacity-80">{citation.snippet}</p>
      </TooltipContent>
    </Tooltip>
  );
}

/** "Sources" row under an answer: one chip per document page the answer cites. */
export function SourceChips({ citations, content }: { citations: Citation[]; content: string }) {
  const referenced = new Set(citedNumbers(content));
  const pages = new Map<string, Citation>();
  for (const c of citations) {
    const key = `${c.slug}#${c.page}`;
    if (referenced.has(c.n) && !pages.has(key)) pages.set(key, c);
  }
  if (pages.size === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">Sources</span>
      {[...pages.values()].map((c) => (
        <a
          key={`${c.slug}#${c.page}`}
          href={pdfUrl(c.slug, c.page)}
          target="_blank"
          rel="noreferrer"
          title={`${c.title} (${c.doc_id}), page ${c.page}`}
          className="inline-flex items-center gap-1 rounded-md border bg-background px-2 py-0.5 text-xs transition-colors hover:border-brand hover:text-brand"
        >
          <FileTextIcon className="size-3" />
          {citationLabel(c)}
        </a>
      ))}
    </div>
  );
}

// Matches [3] and [1, 2] but not markdown links like [text](url).
const CITE_RE = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\](?!\()/g;

export function citedNumbers(content: string): number[] {
  return [...content.matchAll(CITE_RE)].flatMap((m) => m[1].split(",").map(Number));
}

/** Turns [n] markers into markdown links (#cite-n) that the renderer swaps for CitationRef. */
export function linkCitations(content: string): string {
  return content.replace(CITE_RE, (_, nums: string) =>
    nums
      .split(",")
      .map((n) => `[${n.trim()}](#cite-${n.trim()})`)
      .join(""),
  );
}
