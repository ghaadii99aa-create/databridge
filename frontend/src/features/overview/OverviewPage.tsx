import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Database, FileText, GitBranch, Upload } from "lucide-react";
import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/endpoints";
import type { Overview } from "@/api/types";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { ScoreValue } from "@/components/ui/QualityBar";
import {
  Button, EmptyState, ErrorState, Figure, LinkButton, LoadingBlock, PageHeader, Panel, SampleTag, Section, Skeleton, StatusBadge,
} from "@/components/ui/primitives";
import { fmtCompact, fmtDate, fmtDuration, fmtInt, fmtRelative } from "@/lib/format";
import { useLoadSample } from "@/lib/hooks";

// Recharts is only downloaded once there is a trend to draw, keeping the first page light.
const TrendLine = lazy(() => import("@/components/charts/Charts").then((m) => ({ default: m.TrendLine })));

const ACTIVITY_ICON = {
  dataset: <Database className="h-3.5 w-3.5" />, run: <GitBranch className="h-3.5 w-3.5" />, report: <FileText className="h-3.5 w-3.5" />,
};

function GettingStarted() {
  const sample = useLoadSample();
  return (
    <EmptyState icon={<Database className="h-6 w-6" />} title="No data yet">
      <p>
        DataBridge takes a CSV or Excel file through validation, cleaning and loading, then lets you explore and report on
        the result. Every figure on this page is calculated from the data you add.
      </p>
      <ol className="mt-4 space-y-1.5 text-ink-soft">
        <li>1. Upload a file, or load the sample retail dataset (synthetic, labelled as sample data).</li>
        <li>2. Review the quality findings.</li>
        <li>3. Create a pipeline to clean the data and load it into the database.</li>
        <li>4. Explore, chart and export the processed records.</li>
      </ol>
      <div className="mt-5 flex flex-wrap gap-2">
        <LinkButton to="/datasets" variant="primary" icon={<Upload className="h-4 w-4" />}>Upload a file</LinkButton>
        <Button onClick={() => sample.mutate()} loading={sample.isPending}>Load sample dataset</Button>
      </div>
    </EmptyState>
  );
}

function Summary({ o }: { o: Overview }) {
  const runsDone = o.runs.succeeded + o.runs.failed;
  return (
    <Panel className="grid grid-cols-2 gap-x-6 gap-y-6 md:grid-cols-5 md:divide-x md:divide-stone md:[&>*:not(:first-child)]:pl-6">
      <Figure label="Datasets" value={fmtInt(o.datasets.total)}
        detail={o.datasets.failed ? `${o.datasets.failed} failed ingestion` : `${o.datasets.ready} ready`} />
      <Figure label="Records ingested" value={fmtCompact(o.records.ingested)} detail={`${fmtInt(o.records.ingested)} raw rows`} />
      <Figure label="Records loaded" value={fmtCompact(o.records.loaded)} detail={`from ${fmtInt(o.records.processed)} processed`} />
      <Figure label="Pipeline runs" value={`${o.runs.succeeded} / ${runsDone}`}
        detail={o.runs.failed ? `${o.runs.failed} failed` : runsDone ? "all succeeded" : "none yet"}
        tone={o.runs.failed ? "bad" : undefined} />
      <div className="col-span-2 md:col-span-1">
        <div className="text-sm text-ink-muted">Quality score</div>
        <div className="mt-1 text-xl"><ScoreValue score={o.quality.score} /></div>
        <div className="mt-0.5 text-xs text-ink-muted" title={o.quality.basis}>
          {o.quality.datasets_assessed ? `row-weighted, ${o.quality.datasets_assessed} dataset(s)` : "no assessments"}
        </div>
      </div>
    </Panel>
  );
}

export default function OverviewPage() {
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["overview"], queryFn: api.overview, refetchInterval: 20_000 });

  return (
    <>
      <PageHeader title="Overview" description="Status of your datasets, pipelines and data quality." />
      {isLoading && <LoadingBlock rows={8} />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {data && data.datasets.total === 0 && <GettingStarted />}
      {data && data.datasets.total > 0 && (
        <>
          <Summary o={data} />
          <div className="mt-8 grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <ChartFrame
              title="Quality score over time"
              subtitle="Every assessment, raw and processed, oldest to newest"
              height={240}
              table={{ headers: ["Assessed", "Dataset", "Stage", "Score"],
                rows: data.quality_trend.map((t) => [fmtDate(t.at), t.dataset, t.stage, t.score]) }}
            >
              {data.quality_trend.length > 1 ? (
                <Suspense fallback={<Skeleton className="h-full w-full" />}><TrendLine valueLabel="Score" domain={[Math.max(0, Math.floor(Math.min(...data.quality_trend.map((t) => t.score)) - 3)), 100]}
                  data={data.quality_trend.map((t) => ({ period: new Date(t.at).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) + ` #${t.id}`, value: t.score }))} /></Suspense>
              ) : (
                <p className="pt-16 text-center text-sm text-ink-muted">A trend appears after a second assessment, for example after a pipeline run.</p>
              )}
            </ChartFrame>

            <Panel padded={false}>
              <div className="flex items-center justify-between px-5 pb-2 pt-5">
                <h2 className="text-md font-semibold">Recent pipeline runs</h2>
                <Link to="/pipelines" className="link text-sm">All pipelines</Link>
              </div>
              {data.recent_runs.length === 0 ? (
                <p className="px-5 pb-5 text-sm text-ink-muted">No runs yet. <Link className="link" to="/pipelines/new">Create a pipeline</Link> to clean and load a dataset.</p>
              ) : (
                <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-stone-line text-left text-ink-muted">
                    <th className="px-5 py-2 font-medium">Run</th><th className="py-2 font-medium">Status</th>
                    <th className="py-2 text-right font-medium">Loaded</th><th className="px-5 py-2 text-right font-medium">Time</th></tr></thead>
                  <tbody>
                    {data.recent_runs.slice(0, 7).map((r) => (
                      <tr key={r.id} className="border-b border-stone last:border-0 hover:bg-paper">
                        <td className="max-w-[180px] px-5 py-2">
                          <Link to={`/runs/${r.id}`} className="block truncate font-medium text-ink hover:text-forest-deep">#{r.id} {r.pipeline_name}</Link>
                          <span className="text-xs text-ink-muted">{fmtRelative(r.created_at)}</span>
                        </td>
                        <td className="py-2"><StatusBadge status={r.status} /></td>
                        <td className="num py-2 text-right">{fmtInt(r.rows_loaded)}</td>
                        <td className="num px-5 py-2 text-right text-ink-muted">{fmtDuration(r.duration_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              )}
            </Panel>
          </div>

          <div className="mt-8 grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
            <Section title="Latest datasets" actions={<Link to="/datasets" className="link text-sm">All datasets</Link>} className="mb-0">
              <div className="panel divide-y divide-stone">
                {data.latest_datasets.map((d) => (
                  <Link key={d.id} to={`/datasets/${d.id}`} className="group flex items-center justify-between gap-4 px-5 py-3 hover:bg-paper">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">{d.name}</span>
                        {d.is_sample && <SampleTag />}
                      </div>
                      <div className="num text-sm text-ink-muted">
                        {d.file_format.toUpperCase()} file, {fmtInt(d.row_count)} rows, {d.column_count} columns
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusBadge status={d.status} />
                      <ArrowUpRight className="h-4 w-4 text-ink-faint group-hover:text-forest" />
                    </div>
                  </Link>
                ))}
              </div>
            </Section>
            <Section title="Activity" className="mb-0">
              <ul className="panel divide-y divide-stone">
                {data.activity.map((a, i) => (
                  <li key={i} className="flex items-start gap-3 px-5 py-2.5">
                    <span className={a.status === "failed" ? "mt-0.5 text-clay-deep" : "mt-0.5 text-ink-muted"}>{ACTIVITY_ICON[a.type]}</span>
                    <span className="flex-1 text-sm text-ink-soft">{a.text}</span>
                    <time className="whitespace-nowrap text-xs text-ink-muted" dateTime={a.at}>{fmtRelative(a.at)}</time>
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </>
      )}
    </>
  );
}
