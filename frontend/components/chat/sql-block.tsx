import { Fragment } from "react";

const KEYWORDS = new Set(
  (
    "select from where join left right inner outer full cross on and or not in is null as " +
    "group by order having limit offset distinct case when then else end like between " +
    "union all exists with asc desc count sum avg min max round coalesce cast date " +
    "strftime julianday ifnull nullif lower upper over partition"
  ).split(" "),
);

// One alternation, tried left to right: comment | string | number | word | anything else.
const TOKEN_RE = /(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][\w]*)|([\s\S])/g;

/** Tiny SQL highlighter: enough for read-only SELECTs, no 100 kB dependency. */
export function SqlBlock({ sql }: { sql: string }) {
  const parts = [...sql.matchAll(TOKEN_RE)].map((m, i) => {
    const [text, comment, str, num, word] = m;
    const cls = comment
      ? "text-muted-foreground italic"
      : str
        ? "text-emerald-700 dark:text-emerald-300"
        : num
          ? "text-sky-700 dark:text-sky-300"
          : word && KEYWORDS.has(word.toLowerCase())
            ? "font-semibold text-brand"
            : undefined;
    return cls ? (
      <span key={i} className={cls}>
        {text}
      </span>
    ) : (
      <Fragment key={i}>{text}</Fragment>
    );
  });

  return (
    <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-5">
      <code>{parts}</code>
    </pre>
  );
}
