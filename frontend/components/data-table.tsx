import { cn } from "@/lib/utils";

type Props = { columns: string[]; rows: unknown[][]; className?: string; dense?: boolean };

/** Plain scrollable table for query results and table previews. */
export function DataTable({ columns, rows, className, dense }: Props) {
  const cell = dense ? "px-2 py-1" : "px-3 py-1.5";
  return (
    <div className={cn("overflow-auto rounded-md border", className)}>
      <table className={cn("w-full font-mono", dense ? "text-[0.7rem]" : "text-xs")}>
        <thead className="sticky top-0 bg-muted">
          <tr>
            {columns.map((c) => (
              <th key={c} className={cn(cell, "text-left font-semibold whitespace-nowrap")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t even:bg-muted/30">
              {row.map((value, j) => (
                <td
                  key={j}
                  className={cn(
                    cell,
                    "max-w-72 truncate whitespace-nowrap",
                    typeof value === "number" && "text-right tabular-nums",
                  )}
                  title={value == null ? undefined : String(value)}
                >
                  {value == null ? <span className="text-muted-foreground/60">NULL</span> : String(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
