import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import type { Agg, SourceColumn, Suitability } from "@/api/types";
import { ChartFrame, GroupedBars, HBarChart, Histogram, TrendLine } from "@/components/charts/Charts";
import { EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Select, Skeleton } from "@/components/ui/primitives";
import { fmtDate, fmtInt, fmtNum } from "@/lib/format";
import { SourcePicker, useSource } from "@/features/explorer/SourcePicker";

const AGG_LABEL: Record<Agg, string> = { count: "Row count", sum: "Sum", mean: "Average", median: "Median" };
const FREQ = { D: "day", W: "week", M: "month", Q: "quarter" };

function Unavailable({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="panel flex min-h-[200px] flex-col justify-center p-6">
      <div className="text-md font-semibold">{title}</div>
      <p className="mt-1 max-w-md text-base text-ink-muted">{reason}</p>
    </div>
  );
}

function ChartState({ q, children, title }: { q: { isLoading: boolean; error: unknown }; children: ReactNode; title: string }) {
  if (q.isLoading) return <div className="panel p-5"><Skeleton className="mb-4 h-5 w-48" /><Skeleton className="h-[260px] w-full" /></div>;
  if (q.error) return q.error instanceof ApiError && q.error.status === 422
    ? <Unavailable title={title} reason={q.error.message} /> : <ErrorState error={q.error} />;
  return <>{children}</>;
}

function MeasurePicker({ numeric, measure, agg, onMeasure, onAgg, idPrefix }: {
  numeric: SourceColumn[]; measure: string; agg: Agg; onMeasure: (v: string) => void; onAgg: (v: Agg) => void; idPrefix: string;
}) {
  return (
    <>
      <Select id={`${idPrefix}-measure`} label="Measure" value={measure} onChange={onMeasure} className="w-44"
        options={[{ value: "", label: "Rows (count)" }, ...numeric.map((c) => ({ value: c.key, label: c.name }))]} />
      {measure && (
        <Select id={`${idPrefix}-agg`} label="Aggregate" value={agg === "count" ? "sum" : agg} onChange={(v) => onAgg(v as Agg)} className="w-32"
          options={(["sum", "mean", "median"] as Agg[]).map((a) => ({ value: a, label: AGG_LABEL[a] }))} />
      )}
    </>
  );
}

function Dashboard({ s }: { s: Suitability }) {
  const src = s.source.id;
  const numeric = s.numeric_columns, cats = s.category_columns, dates = s.datetime_columns;
  const name = (k: string) => s.source.columns.find((c) => c.key === k)?.name ?? k;

  const [catCol, setCatCol] = useState(cats[0]?.key ?? "");
  const [catMeasure, setCatMeasure] = useState(numeric.find((c) => /revenue|amount|sales|total/i.test(c.name))?.key ?? "");
  const [catAgg, setCatAgg] = useState<Agg>("sum");
  const [distCol, setDistCol] = useState(numeric[0]?.key ?? "");
  const [dateCol, setDateCol] = useState(dates[0]?.key ?? "");
  const [tsMeasure, setTsMeasure] = useState(catMeasure);
  const [tsAgg, setTsAgg] = useState<Agg>("sum");
  const [cmpA, setCmpA] = useState(cats[0]?.key ?? "");
  // default split: the most detailed column that still fits the six-series palette (and isn't the group column)
  const defaultSplit = (a: string) => [...cats].filter((c) => c.key !== a && c.distinct >= 2 && c.distinct <= 6)
    .sort((x, y) => y.distinct - x.distinct)[0]?.key ?? cats.find((c) => c.key !== a)?.key ?? "";
  const [cmpB, setCmpB] = useState(defaultSplit(cats[0]?.key ?? ""));

  useEffect(() => {
    setCatCol(cats[0]?.key ?? ""); setDistCol(numeric[0]?.key ?? ""); setDateCol(dates[0]?.key ?? "");
    setCmpA(cats[0]?.key ?? ""); setCmpB(defaultSplit(cats[0]?.key ?? ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  const catQ = useQuery({ queryKey: ["cat", src, catCol, catMeasure, catAgg], enabled: !!catCol,
    queryFn: () => api.analytics.category(src, catCol, catMeasure || undefined, catMeasure ? catAgg : "count") });
  const distQ = useQuery({ queryKey: ["dist", src, distCol], enabled: !!distCol, queryFn: () => api.analytics.distribution(src, distCol) });
  const tsQ = useQuery({ queryKey: ["ts", src, dateCol, tsMeasure, tsAgg], enabled: !!dateCol,
    queryFn: () => api.analytics.timeseries(src, dateCol, tsMeasure || undefined, tsMeasure ? tsAgg : "count") });
  const cmpQ = useQuery({ queryKey: ["cmp", src, cmpA, cmpB, catMeasure, catAgg], enabled: !!cmpA && !!cmpB && cmpA !== cmpB,
    queryFn: () => api.analytics.comparison(src, cmpA, cmpB, catMeasure || undefined, catMeasure ? catAgg : "count") });

  const measureLabel = (m: string, a: Agg) => (m ? `${AGG_LABEL[a === "count" ? "sum" : a]} of ${name(m)}` : "Rows");
  const catOptions = cats.map((c) => ({ value: c.key, label: c.name }));

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-2">
      {/* Category breakdown */}
      <div>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          {cats.length > 0 && <Select id="cat-col" label="Category" value={catCol} onChange={setCatCol} className="w-44" options={catOptions} />}
          {cats.length > 0 && <MeasurePicker idPrefix="cat" numeric={numeric} measure={catMeasure} agg={catAgg} onMeasure={setCatMeasure} onAgg={setCatAgg} />}
        </div>
        {!s.charts.category.available ? <Unavailable title="Category breakdown" reason={s.charts.category.reason} /> : (
          <ChartState q={catQ} title="Category breakdown">
            {catQ.data && (
              <ChartFrame title={`${measureLabel(catMeasure, catAgg)} by ${name(catCol)}`}
                subtitle={`${catQ.data.distinct} distinct value(s)${catQ.data.total != null ? `, total ${fmtNum(catQ.data.total)}` : ""}`}
                height={Math.max(220, catQ.data.items.length * 30)}
                table={{ headers: [name(catCol), measureLabel(catMeasure, catAgg)], rows: catQ.data.items.map((i) => [i.label, i.value]) }}>
                <HBarChart data={catQ.data.items} valueLabel={measureLabel(catMeasure, catAgg)} />
              </ChartFrame>
            )}
          </ChartState>
        )}
      </div>

      {/* Distribution */}
      <div>
        <div className="mb-3 flex flex-wrap items-end gap-3">
          {numeric.length > 0 && <Select id="dist-col" label="Numeric column" value={distCol} onChange={setDistCol} className="w-52"
            options={numeric.map((c) => ({ value: c.key, label: c.name }))} />}
        </div>
        {!s.charts.distribution.available ? <Unavailable title="Distribution" reason={s.charts.distribution.reason} /> : (
          <ChartState q={distQ} title="Distribution">
            {distQ.data && (
              <ChartFrame title={`Distribution of ${name(distCol)}`}
                subtitle={`${fmtInt(distQ.data.count)} values, median ${fmtNum(distQ.data.stats.median)}, mean ${fmtNum(distQ.data.stats.mean)}`}
                footer={distQ.data.note}
                table={{ headers: ["From", "To", "Rows"], rows: distQ.data.bins.map((b) => [fmtNum(b.start), b.end, b.count]) }}>
                <Histogram bins={distQ.data.bins} valueName={name(distCol)} />
              </ChartFrame>
            )}
          </ChartState>
        )}
      </div>

      {/* Time series */}
      <div className="xl:col-span-2">
        <div className="mb-3 flex flex-wrap items-end gap-3">
          {dates.length > 0 && <Select id="ts-col" label="Date column" value={dateCol} onChange={setDateCol} className="w-48"
            options={dates.map((c) => ({ value: c.key, label: c.name }))} />}
          {dates.length > 0 && <MeasurePicker idPrefix="ts" numeric={numeric} measure={tsMeasure} agg={tsAgg} onMeasure={setTsMeasure} onAgg={setTsAgg} />}
        </div>
        {!s.charts.timeseries.available ? <Unavailable title="Trend over time" reason={s.charts.timeseries.reason} /> : (
          <ChartState q={tsQ} title="Trend over time">
            {tsQ.data && (
              <ChartFrame title={`${measureLabel(tsMeasure, tsAgg)} per ${FREQ[tsQ.data.freq]}`}
                subtitle={`${fmtDate(tsQ.data.start, false)} to ${fmtDate(tsQ.data.end, false)}, grouped by ${FREQ[tsQ.data.freq]} from ${name(dateCol)}`}
                table={{ headers: ["Period starting", measureLabel(tsMeasure, tsAgg)], rows: tsQ.data.points.map((p) => [p.period, p.value ?? "—"]) }}>
                <TrendLine data={tsQ.data.points} valueLabel={measureLabel(tsMeasure, tsAgg)} />
              </ChartFrame>
            )}
          </ChartState>
        )}
      </div>

      {/* Comparison */}
      <div className="xl:col-span-2">
        <div className="mb-3 flex flex-wrap items-end gap-3">
          {cats.length > 1 && <>
            <Select id="cmp-a" label="Group by" value={cmpA} onChange={(v) => { setCmpA(v); if (v === cmpB) setCmpB(defaultSplit(v)); }} className="w-44" options={catOptions} />
            <Select id="cmp-b" label="Split by" value={cmpB} onChange={setCmpB} className="w-44" options={catOptions.map((o) => ({ ...o, disabled: o.value === cmpA }))} />
            <span className="pb-2 text-sm text-ink-muted">Measure follows the category chart: {measureLabel(catMeasure, catAgg).toLowerCase()}</span>
          </>}
        </div>
        {cats.length < 2 ? <Unavailable title="Comparison" reason="Comparison needs two category columns; this source has fewer." /> : (
          <ChartState q={cmpQ} title="Comparison">
            {cmpQ.data && (
              <ChartFrame title={`${measureLabel(catMeasure, catAgg)} by ${name(cmpA)} and ${name(cmpB)}`}
                subtitle="Largest groups shown; up to six split values"
                height={320}
                table={{ headers: [name(cmpA), ...cmpQ.data.series], rows: cmpQ.data.rows.map((r) => [r.label, ...cmpQ.data!.series.map((k) => Number(r[k]))]) }}>
                <GroupedBars rows={cmpQ.data.rows} series={cmpQ.data.series} />
              </ChartFrame>
            )}
          </ChartState>
        )}
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  const { sources, source, sourceId, setSource, isLoading } = useSource();
  const suit = useQuery({ queryKey: ["suitability", sourceId], queryFn: () => api.analytics.suitability(sourceId!), enabled: !!sourceId });

  return (
    <>
      <PageHeader title="Analytics" description="Charts computed on the server from the selected source. If a chart needs a column type the source lacks, it says so instead of drawing."
        actions={sources.length > 0 && <SourcePicker sources={sources} value={sourceId} onChange={setSource} />} />
      {isLoading && <LoadingBlock />}
      {!isLoading && sources.length === 0 && (
        <EmptyState title="No data to chart">Add a dataset and run a pipeline; charts read processed, typed data best. <Link className="link" to="/datasets">Go to datasets</Link></EmptyState>
      )}
      {source?.kind === "raw" && (
        <div className="mb-6"><Notice tone="warn">You are charting raw data. Values are parsed on the fly, and duplicates or inconsistent categories are still present. Use a processed source for reporting.</Notice></div>
      )}
      {source?.is_sample && <p className="mb-4 text-sm text-ink-muted">Charts below are built from the synthetic sample dataset.</p>}
      {suit.isLoading && <LoadingBlock rows={8} />}
      {suit.error && <ErrorState error={suit.error} />}
      {suit.data && <Dashboard key={suit.data.source.id} s={suit.data} />}
    </>
  );
}
