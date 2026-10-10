import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationRef, linkCitations } from "@/components/chat/citations";
import type { Citation } from "@/lib/api/types";

type Props = { content: string; citations: Citation[] };

/**
 * Renders an answer as GitHub-flavoured markdown (tables!). Raw HTML in model output
 * is NOT rendered (react-markdown's default), so a prompt-injected <script> stays text.
 * memo: while streaming, only the message receiving tokens re-parses its markdown.
 */
export const Markdown = memo(function Markdown({ content, citations }: Props) {
  const byNumber = new Map(citations.map((c) => [c.n, c]));

  const components: Components = {
    a({ href, children }) {
      if (href?.startsWith("#cite-")) {
        const n = Number(href.slice("#cite-".length));
        return <CitationRef n={n} citation={byNumber.get(n)} />;
      }
      return (
        <a href={href} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
    table({ children }) {
      return (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">{children}</table>
        </div>
      );
    },
    th({ children, style }) {
      return (
        <th style={style} className="border-b bg-muted/50 px-3 py-1.5 text-left font-medium whitespace-nowrap">
          {children}
        </th>
      );
    },
    td({ children, style }) {
      return (
        <td style={style} className="border-b px-3 py-1.5 align-top tabular-nums [tr:last-child>&]:border-0">
          {children}
        </td>
      );
    },
  };

  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {linkCitations(content)}
      </ReactMarkdown>
    </div>
  );
});
