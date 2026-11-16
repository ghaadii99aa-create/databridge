import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, FileText, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/endpoints";
import type { ReportKind } from "@/api/types";
import { useToast } from "@/components/ui/overlays";
import {
  Button, EmptyState, ErrorState, LinkButton, LoadingBlock, PageHeader, Panel, Section, Select,
} from "@/components/ui/primitives";
import { fmtBytes, fmtDate } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";

const KINDS: { value: ReportKind; label: string; description: string }[] = [
  { value: "dataset_summary", label: "Dataset summary", description: "File details, column profile and raw data quality." },
  { value: "quality", label: "Data quality", description: "Score breakdown with its basis, and every finding with a recommendation." },
  { value: "pipeline_run", label: "Pipeline run", description: "Rows in and out, quality before and after, stage timings and the full log." },
];

export default function ReportsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [kind, setKind] = useState<ReportKind>("dataset_summary");
  const [format, setFormat] = useState<"pdf" | "csv">("pdf");
  const [target, setTarget] = useState("");

  const reports = useQuery({ queryKey: ["reports"], queryFn: api.reports.list });
  const datasets = useQuery({ queryKey: ["datasets", ""], queryFn: () => api.datasets.list() });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.pipelines.runs() });
  const pipelines = useQuery({ queryKey: ["pipelines"], queryFn: api.pipelines.list });

  const options = kind === "pipeline_run"
    ? (runs.data ?? []).filter((r) => r.status === "succeeded" || r.status === "failed").map((r) => ({
        value: String(r.id), label: `Run #${r.id}, ${pipelines.data?.find((p) => p.id === r.pipeline_id)?.name ?? "pipeline"} (${r.status})` }))
    : (datasets.data ?? []).filter((d) => d.status === "ready").map((d) => ({ value: String(d.id), label: d.name }));
  useEffect(() => { setTarget(options[0]?.value ?? ""); }, [kind, options.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const create = useMutation({
    mutationFn: () => api.reports.create({ kind, format,
      ...(kind === "pipeline_run" ? { run_id: Number(target) } : { dataset_id: Number(target) }) }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["reports"] }); toast("success", `Report generated: ${r.title}`); },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.reports.remove(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["reports"] }); toast("success", "Report deleted"); },
    onError: (e) => toast("error", errorMessage(e)),
  });

  return (
    <>
      <PageHeader title="Reports" description="Generate PDF or CSV reports from stored results. Every figure in a report can be traced to the database." />
      <Section title="Generate a report">
        <Panel className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <fieldset>
            <legend className="label">Report type</legend>
            <div className="space-y-1">
              {KINDS.map((k) => (
                <label key={k.value} className="flex cursor-pointer items-start gap-3 rounded px-2 py-2 hover:bg-paper">
                  <input type="radio" name="kind" value={k.value} checked={kind === k.value} onChange={() => setKind(k.value)} className="mt-1 accent-forest" />
                  <span><span className="block font-medium text-ink">{k.label}</span><span className="block text-sm text-ink-muted">{k.description}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex flex-col gap-4">
            <Select id="rep-target" label={kind === "pipeline_run" ? "Run" : "Dataset"} value={target} onChange={setTarget}
              options={options.length ? options : [{ value: "", label: kind === "pipeline_run" ? "No finished runs yet" : "No ready datasets yet", disabled: true }]} />
            <Select id="rep-format" label="Format" value={format} onChange={(v) => setFormat(v as "pdf" | "csv")}
              options={[{ value: "pdf", label: "PDF, formatted for reading and sharing" }, { value: "csv", label: "CSV, the underlying table for spreadsheets" }]} />
            <div><Button variant="primary" disabled={!target} loading={create.isPending} onClick={() => create.mutate()}>Generate report</Button></div>
          </div>
        </Panel>
      </Section>

      <Section title="Generated reports">
        {reports.isLoading && <LoadingBlock />}
        {reports.error && <ErrorState error={reports.error} onRetry={reports.refetch} />}
        {reports.data?.length === 0 && <EmptyState title="No reports yet">Reports you generate here, or from the quality and run pages, are kept in this list.</EmptyState>}
        {reports.data && reports.data.length > 0 && (
          <ul className="panel divide-y divide-stone">
            {reports.data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-4 px-5 py-3">
                {r.format === "pdf" ? <FileText className="h-5 w-5 text-clay" aria-hidden /> : <FileSpreadsheet className="h-5 w-5 text-forest" aria-hidden />}
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{r.title}</div>
                  <div className="text-sm text-ink-muted">{KINDS.find((k) => k.value === r.kind)?.label}, {r.format.toUpperCase()}, {fmtBytes(r.size_bytes)}, {fmtDate(r.created_at)}</div>
                </div>
                <LinkButton size="sm" href={api.reports.downloadUrl(r.id)} icon={<Download className="h-3.5 w-3.5" />}>Download</LinkButton>
                {!r.read_only && <Button size="sm" variant="ghost" aria-label={`Delete ${r.title}`} onClick={() => remove.mutate(r.id)} icon={<Trash2 className="h-3.5 w-3.5" />} />}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
