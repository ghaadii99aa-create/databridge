import clsx from "clsx";
import { useState, type ReactNode } from "react";

import { fmtNum } from "@/lib/format";

/** Chart with a table view, so values are never conveyed by colour or shape alone. */
export function ChartFrame({ title, subtitle, table, children, height = 280, footer }: {
  title: string; subtitle?: ReactNode; table: { headers: string[]; rows: (string | number)[][] };
  children: ReactNode; height?: number; footer?: ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <figure className="panel min-w-0 p-5">
      <figcaption className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-md font-semibold text-ink">{title}</div>
          {subtitle && <div className="mt-0.5 text-sm text-ink-muted">{subtitle}</div>}
        </div>
        <div className="flex rounded border border-stone-dark p-0.5 text-sm" role="tablist" aria-label="View">
          {(["chart", "table"] as const).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={clsx("rounded-sm px-2.5 py-0.5", view === v ? "bg-ink text-paper" : "text-ink-soft hover:text-ink")}>
              {v === "chart" ? "Chart" : "Table"}
            </button>
          ))}
        </div>
      </figcaption>
      {view === "chart" ? (
        <div style={{ height }}>{children}</div>
      ) : (
        <div className="overflow-auto" style={{ maxHeight: height }}>
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-ink">
                {table.headers.map((h, i) => <th key={h} className={clsx("py-1.5 pr-3 font-medium text-ink-muted", i ? "text-right" : "text-left")}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-b border-stone">
                  {r.map((c, j) => <td key={j} className={clsx("py-1.5 pr-3", j ? "num text-right" : "")}>{typeof c === "number" ? fmtNum(c) : c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {footer && <div className="mt-3 text-xs text-ink-muted">{footer}</div>}
    </figure>
  );
}

