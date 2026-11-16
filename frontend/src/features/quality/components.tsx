import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FileDown } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/api/endpoints";
import type { Assessment, QualityIssue, ReportKind, Severity } from "@/api/types";
import { useToast } from "@/components/ui/overlays";
import { DIMENSIONS, QualityBar, ScoreValue } from "@/components/ui/QualityBar";
import { Button } from "@/components/ui/primitives";
import { fmtInt, fmtPct } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";

const SEV_STYLE: Record<Severity, string> = {
  critical: "bg-[#6E3F2D] text-white", high: "bg-clay-deep text-white", medium: "bg-clay-soft text-clay-deep",
  low: "bg-stone text-ink-soft", info: "bg-[#E4EAF2] text-[#38557A]",
};
const SEV_LABEL: Record<Severity, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low", info: "Info" };

export function SeverityTag({ severity }: { severity: Severity }) {
  return <span className={clsx("inline-flex h-5 w-16 items-center justify-center rounded-sm text-2xs font-semibold", SEV_STYLE[severity])}>{SEV_LABEL[severity]}</span>;
}

/** Score, weighted bar and the counts behind each dimension, so the number can be checked by hand. */
export function ScoreBreakdown({ a }: { a: Assessment }) {
  const c = a.details.counts;
  const basis: Record<string, string> = {
    completeness: `${fmtInt(c.missing_cells)} missing of ${fmtInt(c.total_cells)} cells`,
    validity: `${fmtInt(c.invalid_cells)} invalid of ${fmtInt(c.typed_cells)} typed cells`,
    uniqueness: `${fmtInt(c.duplicate_rows)} duplicate of ${fmtInt(a.row_count)} rows`,
    consistency: `${fmtInt(c.inconsistent_cells)} inconsistent of ${fmtInt(c.textlike_cells)} text cells`,
  };
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8 lg:grid-cols-[200px_minmax(0,1fr)]">
      <div>
        <div className="text-sm text-ink-muted">Quality score</div>
        <ScoreValue score={a.score} className="block text-[3.25rem] leading-none tracking-tight" />
        <div className="mt-3 space-y-0.5 text-sm text-ink-muted">
          <div className="num">{fmtInt(a.total_issues)} scored issue(s)</div>
          <div className="num">{fmtInt(a.affected_rows)} rows affected ({fmtPct(a.affected_rows / Math.max(1, a.row_count))})</div>
        </div>
      </div>
      <div>
        <QualityBar scores={a} />
        <dl className="mt-4 grid gap-x-[2px] text-xs text-ink-muted sm:flex">
          {DIMENSIONS.map((d) => (
            <div key={d.key} style={{ width: `${d.weight * 100}%` }} className="min-w-0 pr-2"><dd className="num">{basis[d.key]}</dd></div>
          ))}
        </dl>
        <p className="mt-4 text-xs text-ink-muted">
          Score = 100 × (0.30 × completeness + 0.30 × validity + 0.20 × uniqueness + 0.20 × consistency). Segment width
          is the weight; fill is the dimension score. Methodology v{a.methodology_version}.
        </p>
      </div>
    </div>
  );
}

export function IssueList({ issues, rowCount }: { issues: QualityIssue[]; rowCount: number }) {
  const [dim, setDim] = useState<string>("all");
  const shown = useMemo(() => issues.filter((i) => dim === "all" || i.dimension === dim), [issues, dim]);
  const dims = ["all", ...DIMENSIONS.map((d) => d.key), "info"];
  if (!issues.length) return <p className="panel px-5 py-6 text-base text-ink-muted">No issues were detected by any check.</p>;
  return (
    <div className="panel">
      <div className="flex flex-wrap gap-1 border-b border-stone-line px-4 py-2.5" role="tablist" aria-label="Filter by dimension">
        {dims.map((d) => {
          const n = d === "all" ? issues.length : issues.filter((i) => i.dimension === d).length;
          return (
            <button key={d} role="tab" aria-selected={dim === d} disabled={!n} onClick={() => setDim(d)}
              className={clsx("rounded px-2.5 py-1 text-sm disabled:opacity-40", dim === d ? "bg-ink text-paper" : "text-ink-soft hover:bg-stone")}>
              {d === "all" ? "All" : d === "info" ? "Informational" : d.charAt(0).toUpperCase() + d.slice(1)} <span className="num opacity-70">{n}</span>
            </button>
          );
        })}
      </div>
      <ul className="divide-y divide-stone">
        {shown.map((i) => (
          <li key={i.id} className="grid grid-cols-[minmax(0,1fr)] gap-3 px-5 py-4 md:grid-cols-[72px_minmax(0,1fr)_120px]">
            <div className="pt-0.5"><SeverityTag severity={i.severity} /></div>
            <div className="min-w-0">
              <p className="text-base text-ink">{i.message}</p>
              <p className="mt-1 text-sm text-ink-muted"><span className="font-medium text-ink-soft">Recommended:</span> {i.recommendation}</p>
              {i.examples.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {i.examples.map((e, k) => <code key={k} className="rounded-sm bg-paper px-1.5 py-0.5 text-xs text-ink-soft ring-1 ring-stone-line">{e}</code>)}
                </div>
              )}
            </div>
            <div className="text-sm md:text-right">
              <div className="num font-medium text-ink">{fmtInt(i.affected_rows)} rows</div>
              <div className="num text-ink-muted">{fmtPct(i.affected_rows / Math.max(1, rowCount))}</div>
              <div className="truncate text-xs text-ink-muted">{i.column_name ?? "All columns"}</div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReportButtons({ kind, datasetId, runId }: { kind: ReportKind; datasetId?: number; runId?: number }) {
  const toast = useToast();
  const qc = useQueryClient();
  const gen = useMutation({
    mutationFn: (format: "pdf" | "csv") => api.reports.create({ kind, format, dataset_id: datasetId, run_id: runId }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      toast("success", `Report generated: ${r.title}`);
      window.location.assign(api.reports.downloadUrl(r.id));
    },
    onError: (e) => toast("error", errorMessage(e)),
  });
  return (
    <div className="flex gap-2">
      <Button size="sm" icon={<FileDown className="h-3.5 w-3.5" />} loading={gen.isPending && gen.variables === "pdf"} onClick={() => gen.mutate("pdf")}>PDF report</Button>
      <Button size="sm" icon={<FileDown className="h-3.5 w-3.5" />} loading={gen.isPending && gen.variables === "csv"} onClick={() => gen.mutate("csv")}>CSV</Button>
    </div>
  );
}
