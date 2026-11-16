import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, Loader2, Play, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/endpoints";
import type { Assessment, RunDetail } from "@/api/types";
import { ScoreValue } from "@/components/ui/QualityBar";
import {
  ErrorState, Figure, LinkButton, LoadingBlock, Notice, PageHeader, Panel, Section, StatusBadge, Button,
} from "@/components/ui/primitives";
import { fmtDate, fmtDuration, fmtInt, TYPE_LABEL } from "@/lib/format";
import { IssueList, ReportButtons, ScoreBreakdown } from "@/features/quality/components";
import { useStartRun } from "./PipelinesPage";

const STAGES = [
  { key: "extract", label: "Extract", does: "Read raw rows from staging" },
  { key: "validate", label: "Validate", does: "Check schema, assess source" },
  { key: "transform", label: "Transform", does: "Apply cleaning rules" },
  { key: "load", label: "Load", does: "Write typed table in one transaction" },
  { key: "profile", label: "Profile", does: "Assess the processed output" },
];

/** The ETL stage track. Stages are a real sequence, so they are numbered. */
function StageTrack({ run }: { run: RunDetail }) {
  return (
    <ol className="grid grid-cols-1 overflow-hidden rounded-md border border-ink/85 sm:grid-cols-5">
      {STAGES.map((s, i) => {
        const done = s.key in (run.stage_timings_ms ?? {});
        const failed = run.error_stage === s.key;
        const active = run.current_stage === s.key && run.status === "running";
        return (
          <li key={s.key} className={clsx("relative border-ink/15 px-4 py-3.5 sm:border-l sm:first:border-l-0",
            "max-sm:border-t max-sm:first:border-t-0",
            failed ? "bg-clay-soft" : done ? "bg-ink text-paper" : active ? "bg-sage" : "bg-surface")}>
            <div className="flex items-center justify-between">
              <span className={clsx("num text-xs", done ? "text-paper/60" : "text-ink-muted")}>{i + 1}</span>
              {done && <Check className="h-3.5 w-3.5 text-sage" aria-label="completed" />}
              {failed && <X className="h-3.5 w-3.5 text-clay-deep" aria-label="failed" />}
              {active && <Loader2 className="h-3.5 w-3.5 animate-spin text-forest-deep" aria-label="running" />}
            </div>
            <div className="mt-1 text-base font-semibold">{s.label}</div>
            <div className={clsx("text-xs", done ? "text-paper/70" : "text-ink-muted")}>{s.does}</div>
            <div className={clsx("num mt-2 text-sm", done ? "text-sage" : "text-ink-faint")}>
              {done ? fmtDuration(run.stage_timings_ms[s.key]) : failed ? "failed" : active ? "running" : "waiting"}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Delta({ before, after, label, digits = 1, invert }: { before: number; after: number; label: string; digits?: number; invert?: boolean }) {
  const d = after - before;
  const better = invert ? d < 0 : d > 0;
  return (
    <tr className="border-b border-stone last:border-0">
      <td className="px-4 py-2 text-ink-soft">{label}</td>
      <td className="num py-2 text-right">{before.toFixed(digits)}</td>
      <td className="num py-2 text-right font-medium">{after.toFixed(digits)}</td>
      <td className={clsx("num px-4 py-2 text-right", d === 0 ? "text-ink-faint" : better ? "text-forest-deep" : "text-clay-deep")}>
        {d > 0 ? "+" : ""}{d.toFixed(digits)}
      </td>
    </tr>
  );
}

function BeforeAfter({ b, a }: { b: Assessment; a: Assessment }) {
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
        <th className="px-4 py-2 font-medium">Measure</th><th className="py-2 text-right font-medium">Source</th>
        <th className="py-2 text-right font-medium">Processed</th><th className="px-4 py-2 text-right font-medium">Change</th></tr></thead>
      <tbody>
        <Delta label="Quality score" before={b.score} after={a.score} />
        <Delta label="Completeness" before={b.completeness} after={a.completeness} digits={2} />
        <Delta label="Validity" before={b.validity} after={a.validity} digits={2} />
        <Delta label="Uniqueness" before={b.uniqueness} after={a.uniqueness} digits={2} />
        <Delta label="Consistency" before={b.consistency} after={a.consistency} digits={2} />
        <Delta label="Scored issues" before={b.total_issues} after={a.total_issues} digits={0} invert />
        <Delta label="Rows affected" before={b.affected_rows} after={a.affected_rows} digits={0} invert />
      </tbody>
    </table>
  );
}

export default function RunPage() {
  const id = Number(useParams().id);
  const start = useStartRun();
  const { data: run, isLoading, error, refetch } = useQuery({
    queryKey: ["run", id], queryFn: () => api.pipelines.run(id),
    refetchInterval: (q) => (q.state.data && ["pending", "running"].includes(q.state.data.status) ? 700 : false),
  });
  const { data: cmp } = useQuery({ queryKey: ["comparison", id], queryFn: () => api.pipelines.comparison(id), enabled: run?.status === "succeeded" });

  if (isLoading) return <LoadingBlock rows={8} />;
  if (error || !run) return <ErrorState error={error} onRetry={refetch} />;
  const live = run.status === "pending" || run.status === "running";

  return (
    <>
      <PageHeader title={`Run #${run.id}: ${run.pipeline_name}`}
        meta={<><Link to="/pipelines" className="link">Pipelines</Link><span>/</span><StatusBadge status={run.status} /><span>source {run.dataset_name}</span></>}
        actions={!live && <>
          <ReportButtons kind="pipeline_run" runId={run.id} />
          {!run.read_only && <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} onClick={() => start.mutate(run.pipeline_id)} loading={start.isPending}>Run again</Button>}
          {run.output && <LinkButton size="sm" variant="primary" to={`/explorer?source=processed-${run.id}`}>Explore output</LinkButton>}
        </>} />

      <Section title="Stages" description={live ? "Updating live while the run is in progress." : `Started ${fmtDate(run.started_at)}, finished in ${fmtDuration(run.duration_ms)}.`}>
        <StageTrack run={run} />
      </Section>

      {run.status === "failed" && (
        <div className="mb-8"><Notice tone="warn">
          <strong className="text-ink">The run failed during {run.error_stage}.</strong> {run.error_message} Nothing was loaded; any partial output table was removed.
        </Notice></div>
      )}

      <Panel className="mb-9 grid grid-cols-2 gap-6 md:grid-cols-4">
        <Figure label="Rows extracted" value={fmtInt(run.rows_extracted)} />
        <Figure label="Rows loaded" value={fmtInt(run.rows_loaded)} detail={run.output ? `into ${run.output.table_name}` : undefined} />
        <Figure label="Rows rejected" value={fmtInt(run.rows_rejected)} detail="by rules, not counting duplicates" />
        <Figure label="Duplicates removed" value={run.rows_extracted != null && run.rows_loaded != null && run.rows_rejected != null
          ? fmtInt(run.rows_extracted - run.rows_loaded - run.rows_rejected) : "—"} />
      </Panel>

      {run.quality_before && run.quality_after && (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Section title="Quality before and after">
            <div className="panel">
              <div className="flex items-end gap-6 border-b border-stone-line px-5 py-4">
                <div><div className="text-sm text-ink-muted">Source</div><ScoreValue score={run.quality_before.score} className="text-xl" /></div>
                <div className="pb-1 text-ink-faint">to</div>
                <div><div className="text-sm text-ink-muted">Processed</div><ScoreValue score={run.quality_after.score} className="text-xl" /></div>
              </div>
              <BeforeAfter b={run.quality_before} a={run.quality_after} />
            </div>
          </Section>
          <Section title="Remaining findings" description="What the processed output still contains, by the same rules.">
            <IssueList issues={run.quality_after.issues} rowCount={run.quality_after.row_count} />
          </Section>
        </div>
      )}

      {cmp && (
        <Section title="Raw and processed columns" description={`${fmtInt(cmp.raw_rows)} raw rows became ${fmtInt(cmp.processed_rows)} processed rows.`}>
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
                <th className="px-4 py-2 font-medium">Column</th><th className="py-2 font-medium">Type</th>
                <th className="py-2 text-right font-medium">Missing (raw → processed)</th><th className="px-4 py-2 text-right font-medium">Distinct (raw → processed)</th></tr></thead>
              <tbody>
                {cmp.columns.map((c) => (
                  <tr key={c.key} className="border-b border-stone last:border-0">
                    <td className="px-4 py-2 font-medium">{c.name}{c.dropped && <span className="ml-2 text-xs text-clay-deep">dropped</span>}</td>
                    <td className="py-2 text-ink-muted">{TYPE_LABEL[c.raw_type]}{c.processed_type && c.processed_type !== c.raw_type ? ` → ${TYPE_LABEL[c.processed_type]}` : ""}</td>
                    <td className="num py-2 text-right">{fmtInt(c.raw_missing)} → {fmtInt(c.processed_missing)}</td>
                    <td className="num px-4 py-2 text-right">{fmtInt(c.raw_distinct)} → {fmtInt(c.processed_distinct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="Execution log" description="Written by the runner as each stage progresses.">
        <div className="overflow-x-auto rounded-md bg-ink text-sm text-paper">
          <table className="w-full min-w-[640px]">
            <tbody>
              {run.logs.map((l) => (
                <tr key={l.id} className="border-b border-paper/10 last:border-0 align-top">
                  <td className="num whitespace-nowrap py-1.5 pl-4 pr-3 text-paper/50">{new Date(l.created_at).toLocaleTimeString("en-GB", { hour12: false })}.{String(new Date(l.created_at).getMilliseconds()).padStart(3, "0")}</td>
                  <td className="w-24 py-1.5 pr-3 text-sage/80">{l.stage}</td>
                  <td className={clsx("py-1.5 pr-4", l.level === "error" ? "text-[#F0B49B]" : l.level === "warning" ? "text-[#E9D49A]" : "text-paper/90")}>{l.message}</td>
                </tr>
              ))}
              {live && <tr><td colSpan={3} className="py-2 pl-4 text-paper/50"><Loader2 className="inline h-3.5 w-3.5 animate-spin" /> waiting for the next stage…</td></tr>}
            </tbody>
          </table>
        </div>
      </Section>

      {run.quality_before && !run.quality_after && (
        <Section title="Source assessment"><Panel><ScoreBreakdown a={run.quality_before} /></Panel></Section>
      )}
    </>
  );
}
