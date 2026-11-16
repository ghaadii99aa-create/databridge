import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, GitBranch, Pencil, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/endpoints";
import type { DatasetDetail } from "@/api/types";
import { ConfirmDialog, useToast } from "@/components/ui/overlays";
import { QualityBar, ScoreValue } from "@/components/ui/QualityBar";
import {
  Badge, Button, ErrorState, LinkButton, LoadingBlock, Notice, PageHeader, Panel, SampleTag, Section, StatusBadge,
} from "@/components/ui/primitives";
import { fmtBytes, fmtDate, fmtDuration, fmtInt, fmtPct, TYPE_LABEL } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";

function Metadata({ d }: { d: DatasetDetail }) {
  const rows: [string, string][] = [
    ["Original file", d.original_filename],
    ["Format", d.file_format === "csv" ? `CSV, ${d.encoding ?? "?"} encoding, delimiter "${d.delimiter === "\t" ? "tab" : d.delimiter}"` : `Excel workbook, sheet "${d.sheet_name}"`],
    ["Size", fmtBytes(d.file_size_bytes)],
    ["SHA-256", d.sha256.slice(0, 16) + "…"],
    ["Ingested", `${fmtDate(d.created_at)} in ${fmtDuration(d.ingest_duration_ms)}`],
  ];
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-sm text-ink-muted">{k}</dt>
          <dd className="truncate text-base text-ink" title={k === "SHA-256" ? d.sha256 : v}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Preview({ id }: { id: number }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["preview", id], queryFn: () => api.datasets.preview(id, 25) });
  if (isLoading) return <LoadingBlock />;
  if (error) return <ErrorState error={error} />;
  if (!data) return null;
  return (
    <div className="panel max-h-[440px] overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-ink/80 text-left">
            <th className="sticky left-0 bg-surface px-3 py-2 text-right font-medium text-ink-faint">#</th>
            {data.columns.map((c) => <th key={c.key} className="whitespace-nowrap px-3 py-2 font-medium text-ink-soft">{c.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i} className="border-b border-stone">
              <td className="num sticky left-0 bg-surface px-3 py-1.5 text-right text-ink-faint">{i + 1}</td>
              {data.columns.map((c) => (
                <td key={c.key} className="whitespace-pre px-3 py-1.5 text-ink">
                  {r[c.key] === "" ? <span className="text-ink-faint">empty</span> : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DatasetDetailPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const { data: d, isLoading, error, refetch } = useQuery({ queryKey: ["dataset", id], queryFn: () => api.datasets.get(id) });
  const { data: quality } = useQuery({ queryKey: ["quality", id], queryFn: () => api.quality.latest(id), enabled: d?.status === "ready" });

  const remove = useMutation({
    mutationFn: () => api.datasets.remove(id),
    onSuccess: () => { qc.invalidateQueries(); toast("success", "Dataset deleted"); navigate("/datasets"); },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const rename = useMutation({
    mutationFn: () => api.datasets.rename(id, name.trim(), d?.description ?? null),
    onSuccess: () => { qc.invalidateQueries(); setEditing(false); toast("success", "Dataset renamed"); },
    onError: (e) => toast("error", errorMessage(e)),
  });

  if (isLoading) return <LoadingBlock rows={8} />;
  if (error || !d) return <ErrorState error={error} onRetry={refetch} />;

  return (
    <>
      <PageHeader
        title={d.name}
        meta={<><Link to="/datasets" className="link">Datasets</Link><span>/</span><StatusBadge status={d.status} />{d.is_sample && <SampleTag />}</>}
        description={d.description ?? undefined}
        actions={d.status === "ready" ? (
          <>
            {!d.read_only && <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => { setName(d.name); setEditing(true); }}>Rename</Button>}
            <LinkButton href={api.datasets.downloadUrl(d.id)} size="sm" icon={<Download className="h-3.5 w-3.5" />}>Original file</LinkButton>
            {!d.read_only && <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirm(true)}>Delete</Button>}
            <LinkButton to={`/pipelines/new?dataset=${d.id}`} size="sm" variant="primary" icon={<GitBranch className="h-3.5 w-3.5" />}>Create pipeline</LinkButton>
          </>
        ) : !d.read_only && <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirm(true)}>Delete</Button>}
      />

      {editing && (
        <form className="mb-6 flex max-w-lg items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) rename.mutate(); }}>
          <div className="flex-1"><label htmlFor="rename" className="label">New name</label>
            <input id="rename" className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} autoFocus /></div>
          <Button type="submit" variant="primary" loading={rename.isPending} disabled={!name.trim()}>Save name</Button>
          <Button type="button" onClick={() => setEditing(false)}>Cancel</Button>
        </form>
      )}

      {d.status === "failed" && (
        <div className="mb-8"><Notice tone="warn">
          <strong className="text-ink">Ingestion failed.</strong> {d.error_message} Fix the file and upload it again.
        </Notice></div>
      )}

      <Section title="File"><Panel><Metadata d={d} /></Panel></Section>

      {d.status === "ready" && (
        <>
          {quality && (
            <Section title="Data quality" description={`${fmtInt(quality.total_issues)} issue(s) affect ${fmtInt(quality.affected_rows)} of ${fmtInt(quality.row_count)} rows (${fmtPct(quality.affected_rows / quality.row_count)}).`}
              actions={<LinkButton to={`/quality?dataset=${d.id}`} size="sm" icon={<ShieldCheck className="h-3.5 w-3.5" />}>Review findings</LinkButton>}>
              <Panel className="grid grid-cols-[minmax(0,1fr)] items-center gap-6 md:grid-cols-[140px_minmax(0,1fr)]">
                <div><div className="text-sm text-ink-muted">Score</div><ScoreValue score={quality.score} className="text-2xl" /></div>
                <QualityBar scores={quality} />
              </Panel>
            </Section>
          )}

          <Section title={`Columns (${d.column_count})`} description="Types are inferred from the values: a type is assigned when at least 90% of non-empty values match it.">
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
                  <th className="px-5 py-2.5 font-medium">Column</th><th className="py-2.5 font-medium">Inferred type</th>
                  <th className="py-2.5 text-right font-medium">Missing</th><th className="py-2.5 text-right font-medium">Distinct</th>
                  <th className="px-5 py-2.5 font-medium">Sample values</th></tr></thead>
                <tbody>
                  {d.columns.map((c) => (
                    <tr key={c.id} className="border-b border-stone last:border-0">
                      <td className="px-5 py-2.5"><div className="font-medium">{c.name}</div><code className="text-xs text-ink-muted">{c.key}</code></td>
                      <td className="py-2.5"><Badge tone={c.inferred_type === "empty" ? "bad" : "neutral"}>{TYPE_LABEL[c.inferred_type]}</Badge></td>
                      <td className="num py-2.5 text-right">
                        {c.null_count ? <span className={c.null_count / d.row_count > 0.2 ? "text-clay-deep" : ""}>{fmtInt(c.null_count)} <span className="text-ink-muted">({fmtPct(c.null_count / d.row_count)})</span></span> : <span className="text-ink-faint">0</span>}
                      </td>
                      <td className="num py-2.5 text-right">{fmtInt(c.distinct_count)}</td>
                      <td className="max-w-[360px] truncate px-5 py-2.5 text-ink-muted" title={c.sample_values.join(", ")}>{c.sample_values.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Raw preview" description="The first 25 rows exactly as read from the file, before any cleaning.">
            <Preview id={d.id} />
          </Section>
        </>
      )}

      <ConfirmDialog open={confirm} title={`Delete "${d.name}"?`} confirmLabel="Delete dataset" danger busy={remove.isPending}
        onCancel={() => setConfirm(false)} onConfirm={() => remove.mutate()}>
        This removes the stored file, the staged rows, {d.pipeline_count} pipeline(s) with their runs and processed tables, and all quality
        results for this dataset. Generated reports are kept. This cannot be undone.
      </ConfirmDialog>
    </>
  );
}
