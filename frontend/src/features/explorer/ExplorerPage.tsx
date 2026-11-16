import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Plus, Search, X } from "lucide-react";
import { useDeferredValue, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/endpoints";
import type { ColumnStat, Filter, FilterOp, SourceColumn } from "@/api/types";
import {
  Badge, Button, EmptyState, ErrorState, LinkButton, LoadingBlock, Notice, PageHeader, Section,
} from "@/components/ui/primitives";
import { fmtInt, fmtNum, fmtPct, formatCell, TYPE_LABEL } from "@/lib/format";
import { SourcePicker, useSource } from "./SourcePicker";

const TYPED = new Set(["integer", "decimal", "datetime", "boolean"]);
const OP_LABEL: Record<FilterOp, string> = {
  eq: "equals", neq: "does not equal", contains: "contains", gt: ">", gte: "≥", lt: "<", lte: "≤",
  is_null: "is empty", not_null: "is not empty",
};
function opsFor(col: SourceColumn | undefined, typed: boolean): FilterOp[] {
  if (!col) return ["eq"];
  if (typed && TYPED.has(col.type)) return ["eq", "neq", "gt", "gte", "lt", "lte", "is_null", "not_null"];
  return ["eq", "neq", "contains", "is_null", "not_null"];
}

function FilterBar({ columns, typed, filters, onChange }: {
  columns: SourceColumn[]; typed: boolean; filters: Filter[]; onChange: (f: Filter[]) => void;
}) {
  const [draft, setDraft] = useState<Filter>({ column: columns[0]?.key ?? "", op: "eq", value: "" });
  useEffect(() => setDraft({ column: columns[0]?.key ?? "", op: "eq", value: "" }), [columns]);
  const col = columns.find((c) => c.key === draft.column);
  const needsValue = !["is_null", "not_null"].includes(draft.op);
  const add = () => {
    if (needsValue && !draft.value?.trim()) return;
    onChange([...filters, { ...draft, value: needsValue ? draft.value?.trim() : undefined }]);
    setDraft({ ...draft, value: "" });
  };
  return (
    <div className="space-y-2">
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <select aria-label="Filter column" className="field h-8 w-44 text-sm" value={draft.column}
          onChange={(e) => setDraft({ column: e.target.value, op: "eq", value: "" })}>
          {columns.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
        </select>
        <select aria-label="Filter operator" className="field h-8 w-36 text-sm" value={draft.op}
          onChange={(e) => setDraft({ ...draft, op: e.target.value as FilterOp })}>
          {opsFor(col, typed).map((o) => <option key={o} value={o}>{OP_LABEL[o]}</option>)}
        </select>
        {needsValue && (
          <input aria-label="Filter value" className="field h-8 w-40 text-sm" value={draft.value ?? ""}
            placeholder={col?.type === "datetime" && typed ? "2025-06-30" : "Value"} onChange={(e) => setDraft({ ...draft, value: e.target.value })} />
        )}
        <Button size="sm" type="submit" icon={<Plus className="h-3.5 w-3.5" />}>Add filter</Button>
      </form>
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {filters.map((f, i) => (
            <span key={i} className="inline-flex h-7 items-center gap-1.5 rounded-sm bg-sage px-2 text-sm text-forest-deep">
              {columns.find((c) => c.key === f.column)?.name} {OP_LABEL[f.op]} {f.value && <strong className="font-medium">{f.value}</strong>}
              <button aria-label="Remove filter" onClick={() => onChange(filters.filter((_, j) => j !== i))} className="hover:text-ink"><X className="h-3.5 w-3.5" /></button>
            </span>
          ))}
          <button className="link text-sm" onClick={() => onChange([])}>Clear all</button>
        </div>
      )}
    </div>
  );
}

function StatsTable({ stats }: { stats: ColumnStat[] }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full min-w-[880px] text-sm">
        <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
          <th className="px-4 py-2 font-medium">Column</th><th className="py-2 font-medium">Type</th>
          <th className="py-2 text-right font-medium">Missing</th><th className="py-2 text-right font-medium">Distinct</th>
          <th className="py-2 text-right font-medium">Min</th><th className="py-2 text-right font-medium">Median</th>
          <th className="py-2 text-right font-medium">Mean</th><th className="py-2 text-right font-medium">Max</th>
          <th className="px-4 py-2 font-medium">Most frequent</th></tr></thead>
        <tbody>
          {stats.map((s) => {
            const date = s.type === "datetime";
            return (
              <tr key={s.key} className="border-b border-stone last:border-0 align-top">
                <td className="px-4 py-2 font-medium">{s.name}</td>
                <td className="py-2 text-ink-muted">{TYPE_LABEL[s.type]}</td>
                <td className="num py-2 text-right">{s.missing ? `${fmtInt(s.missing)} (${fmtPct(s.missing_ratio)})` : <span className="text-ink-faint">0</span>}</td>
                <td className="num py-2 text-right">{fmtInt(s.distinct)}</td>
                <td className="num py-2 text-right">{date ? String(s.min ?? "").slice(0, 10) : fmtNum(s.min as number | undefined)}</td>
                <td className="num py-2 text-right">{fmtNum(s.median)}</td>
                <td className="num py-2 text-right">{fmtNum(s.mean)}</td>
                <td className="num py-2 text-right">{date ? String(s.max ?? "").slice(0, 10) : fmtNum(s.max as number | undefined)}</td>
                <td className="max-w-[260px] px-4 py-2 text-ink-muted">
                  {s.top_values?.slice(0, 3).map((t) => `${t.value} (${fmtInt(t.count)})`).join(", ") ?? (date ? `${s.span_days} day span` : "")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function ExplorerPage() {
  const { sources, source, sourceId, setSource, isLoading: loadingSources } = useSource();
  const [tab, setTab] = useState<"rows" | "stats">("rows");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filter[]>([]);
  const [sort, setSort] = useState<{ key: string; order: "asc" | "desc" } | null>(null);
  const q = useDeferredValue(search);

  useEffect(() => { setPage(1); setFilters([]); setSort(null); setSearch(""); }, [sourceId]);
  useEffect(() => setPage(1), [q, filters, sort, pageSize]);

  const rows = useQuery({
    queryKey: ["rows", sourceId, page, pageSize, q, filters, sort],
    queryFn: () => api.explorer.rows({ source: sourceId!, page, page_size: pageSize, search: q || undefined, filters,
      sort: sort?.key, order: sort?.order }),
    enabled: !!sourceId, placeholderData: keepPreviousData,
  });
  const stats = useQuery({ queryKey: ["stats", sourceId], queryFn: () => api.explorer.stats(sourceId!), enabled: !!sourceId && tab === "stats" });
  const meta = rows.data?.source;
  const typed = source?.kind === "processed";

  const toggleSort = (key: string) =>
    setSort((s) => (s?.key !== key ? { key, order: "asc" } : s.order === "asc" ? { key, order: "desc" } : null));

  return (
    <>
      <PageHeader title="Explorer" description="Browse raw and processed data. Filtering, sorting and paging run as SQL on the server; only the visible page is sent to the browser."
        actions={sources.length > 0 && <>
          <SourcePicker sources={sources} value={sourceId} onChange={setSource} />
          {sourceId && <LinkButton href={api.explorer.exportUrl(sourceId)} icon={<Download className="h-4 w-4" />}>Export CSV</LinkButton>}
        </>} />

      {loadingSources && <LoadingBlock />}
      {!loadingSources && sources.length === 0 && (
        <EmptyState title="No data to explore">Upload a dataset on the <Link to="/datasets" className="link">Datasets</Link> page first.</EmptyState>
      )}

      {source && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            <Badge tone={typed ? "good" : "neutral"}>{typed ? "Processed, typed columns" : "Raw, values as uploaded"}</Badge>
            <span>{fmtInt(source.row_count)} rows, {source.column_count} columns</span>
            {typed && source.run_id && <Link to={`/runs/${source.run_id}`} className="link">View run #{source.run_id} and the raw comparison</Link>}
          </div>
          <div className="mb-4 flex gap-1 border-b border-stone-line" role="tablist">
            {(["rows", "stats"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                className={clsx("-mb-px border-b-2 px-3 py-2 text-base", tab === t ? "border-forest font-medium text-ink" : "border-transparent text-ink-muted hover:text-ink")}>
                {t === "rows" ? "Rows" : "Column statistics"}
              </button>
            ))}
          </div>

          {tab === "stats" && (stats.isLoading ? <LoadingBlock rows={6} /> : stats.error ? <ErrorState error={stats.error} /> : stats.data && <StatsTable stats={stats.data.columns} />)}

          {tab === "rows" && meta && (
            <Section title="" className="mb-0">
              <div className="mb-3 flex flex-col gap-3">
                <div className="relative w-full max-w-sm">
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" aria-hidden />
                  <input className="field pl-8" placeholder="Search text columns" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search rows" />
                </div>
                <FilterBar columns={meta.columns} typed={typed} filters={filters} onChange={setFilters} />
                {!typed && <p className="text-xs text-ink-muted">Raw values are text, so numeric and date comparisons are available on processed sources only.</p>}
              </div>
              {rows.error && <ErrorState error={rows.error} />}
              <div className={clsx("panel max-h-[620px] overflow-auto transition-opacity", rows.isFetching && "opacity-70")}>
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 bg-surface">
                    <tr className="border-b border-ink/80">
                      <th className="sticky left-0 z-20 bg-surface px-3 py-2 text-right font-medium text-ink-faint">#</th>
                      {meta.columns.map((c) => {
                        const numeric = typed && (c.type === "integer" || c.type === "decimal");
                        return (
                          <th key={c.key} className={clsx("whitespace-nowrap px-3 py-2 font-medium", numeric ? "text-right" : "text-left")}
                            aria-sort={sort?.key === c.key ? (sort.order === "asc" ? "ascending" : "descending") : "none"}>
                            <button onClick={() => toggleSort(c.key)} className="inline-flex items-center gap-1 text-ink-soft hover:text-ink" title={`${TYPE_LABEL[c.type]}. Click to sort.`}>
                              {c.name}
                              {sort?.key === c.key && (sort.order === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                            </button>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.data?.rows.map((r) => (
                      <tr key={String(r._row_id)} className="border-b border-stone hover:bg-paper">
                        <td className="num sticky left-0 bg-surface px-3 py-1.5 text-right text-ink-faint">{String(r._row_id)}</td>
                        {meta.columns.map((c) => {
                          const v = r[c.key];
                          const numeric = typed && (c.type === "integer" || c.type === "decimal");
                          return (
                            <td key={c.key} className={clsx("whitespace-nowrap px-3 py-1.5", numeric && "num text-right")}>
                              {v === null || v === "" ? <span className="text-ink-faint">empty</span> : formatCell(v, typed ? c.type : undefined)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rows.data && rows.data.total === 0 && <div className="px-5 py-8 text-center text-ink-muted">No rows match the current search and filters.</div>}
              </div>
              {rows.data && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-muted">
                  <span className="num">
                    {rows.data.total ? `${fmtInt((page - 1) * pageSize + 1)}–${fmtInt(Math.min(page * pageSize, rows.data.total))} of ${fmtInt(rows.data.total)} rows` : "0 rows"}
                    {rows.data.total !== source.row_count && ` (filtered from ${fmtInt(source.row_count)})`}
                  </span>
                  <div className="flex items-center gap-2">
                    <select aria-label="Rows per page" className="field h-8 w-24 text-sm" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>
                      {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} / page</option>)}
                    </select>
                    <Button size="sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /></Button>
                    <span className="num">Page {page} of {fmtInt(rows.data.pages)}</span>
                    <Button size="sm" variant="ghost" aria-label="Next page" disabled={page >= rows.data.pages} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></Button>
                  </div>
                </div>
              )}
            </Section>
          )}
          {tab === "rows" && !meta && rows.isLoading && <LoadingBlock rows={10} />}
          {tab === "rows" && !typed && sources.some((s) => s.dataset_id === source.dataset_id && s.kind === "processed") && (
            <div className="mt-6"><Notice>A processed version of this dataset exists. Switch source above to compare.</Notice></div>
          )}
        </>
      )}
    </>
  );
}
