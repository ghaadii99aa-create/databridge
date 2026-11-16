import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "@/api/endpoints";
import { useToast } from "@/components/ui/overlays";
import { ScoreValue } from "@/components/ui/QualityBar";
import {
  Badge, Button, EmptyState, ErrorState, LinkButton, LoadingBlock, PageHeader, Panel, SampleTag, Section, Select,
} from "@/components/ui/primitives";
import { fmtDate, fmtInt, TYPE_LABEL } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";
import { IssueList, ReportButtons, ScoreBreakdown } from "./components";

function Methodology() {
  const { data } = useQuery({ queryKey: ["methodology"], queryFn: api.quality.methodology, staleTime: Infinity });
  if (!data) return null;
  return (
    <details className="panel group">
      <summary className="cursor-pointer list-none px-5 py-3.5 text-base font-medium text-ink marker:hidden">
        How the score is calculated <span className="text-ink-muted group-open:hidden">(show rules)</span>
      </summary>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-8 border-t border-stone-line px-5 py-5 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Dimensions</h3>
          <dl className="space-y-2 text-sm">
            {Object.entries(data.dimensions).map(([k, v]) => (
              <div key={k}><dt className="font-medium capitalize text-ink">{k} ({Math.round(data.weights[k as keyof typeof data.weights] * 100)}%)</dt><dd className="text-ink-muted">{v}</dd></div>
            ))}
          </dl>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Checks</h3>
          <dl className="space-y-2 text-sm">
            {Object.entries(data.checks).map(([k, c]) => (
              <div key={k}><dt className="font-medium text-ink">{c.title} <span className="font-normal text-ink-faint">({c.dimension})</span></dt><dd className="text-ink-muted">{c.rule}</dd></div>
            ))}
          </dl>
        </div>
      </div>
    </details>
  );
}

export default function QualityPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: datasets, isLoading: dsLoading } = useQuery({ queryKey: ["datasets", ""], queryFn: () => api.datasets.list() });
  const ready = (datasets ?? []).filter((d) => d.status === "ready");
  const selected = Number(params.get("dataset")) || ready[0]?.id;

  useEffect(() => {
    if (!params.get("dataset") && ready[0]) setParams({ dataset: String(ready[0].id) }, { replace: true });
  }, [ready, params, setParams]);

  const { data: a, isLoading, error, refetch } = useQuery({
    queryKey: ["quality", selected], queryFn: () => api.quality.latest(selected!), enabled: !!selected,
  });
  const { data: history } = useQuery({ queryKey: ["quality-history", selected], queryFn: () => api.quality.history(selected!), enabled: !!selected });
  const rerun = useMutation({
    mutationFn: () => api.quality.run(selected!),
    onSuccess: (res) => { qc.invalidateQueries(); toast("success", `Assessment complete: score ${res.score}`); },
    onError: (e) => toast("error", errorMessage(e)),
  });
  const ds = ready.find((d) => d.id === selected);

  return (
    <>
      <PageHeader title="Data quality"
        description="Rule-based checks for completeness, validity, uniqueness and consistency, with the evidence behind every finding."
        actions={ds && <>
          <Select value={String(selected)} onChange={(v) => setParams({ dataset: v })} className="w-64" id="quality-dataset"
            options={ready.map((d) => ({ value: String(d.id), label: d.name }))} />
          {!ds.read_only && <Button icon={<RefreshCw className="h-4 w-4" />} onClick={() => rerun.mutate()} loading={rerun.isPending}>Re-assess</Button>}
        </>} />

      {dsLoading && <LoadingBlock />}
      {!dsLoading && ready.length === 0 && (
        <EmptyState title="Nothing to assess yet">Quality checks run automatically when a dataset is uploaded. <Link to="/datasets" className="link">Add a dataset</Link> to begin.</EmptyState>
      )}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {isLoading && selected && <LoadingBlock rows={6} />}

      {a && ds && (
        <>
          <Section title="Raw data assessment"
            description={<span className="inline-flex flex-wrap items-center gap-2">{ds.name} {ds.is_sample && <SampleTag />} <span>assessed {fmtDate(a.created_at)}, {fmtInt(a.row_count)} rows</span></span>}
            actions={<ReportButtons kind="quality" datasetId={ds.id} />}>
            <Panel><ScoreBreakdown a={a} /></Panel>
          </Section>

          <div className="grid grid-cols-[minmax(0,1fr)] gap-8 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Section title="Findings" description="Most severe first. Informational findings, such as outliers, do not lower the score.">
              <IssueList issues={a.issues} rowCount={a.row_count} />
            </Section>
            <div>
              <Section title="Affected columns">
                <div className="panel overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
                      <th className="px-4 py-2 font-medium">Column</th><th className="py-2 text-right font-medium">Missing</th>
                      <th className="py-2 text-right font-medium">Invalid</th><th className="px-4 py-2 text-right font-medium">Inconsistent</th></tr></thead>
                    <tbody>
                      {a.details.columns.map((c) => (
                        <tr key={c.key} className="border-b border-stone last:border-0">
                          <td className="px-4 py-2"><div className="font-medium">{c.name}</div><div className="text-xs text-ink-muted">{TYPE_LABEL[c.type]}</div></td>
                          {[c.missing, c.invalid, c.inconsistent].map((v, i) => (
                            <td key={i} className={`num py-2 text-right ${i === 2 ? "px-4" : ""} ${v ? "text-ink" : "text-ink-faint"}`}>{fmtInt(v)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
              {history && history.length > 0 && (
                <Section title="Assessment history" description="Processed scores come from pipeline runs.">
                  <ul className="panel divide-y divide-stone text-sm">
                    {[...history].reverse().slice(0, 8).map((h) => (
                      <li key={h.id} className="flex items-center justify-between gap-3 px-4 py-2">
                        <span className="text-ink-muted">{fmtDate(h.created_at)}</span>
                        <Badge tone={h.stage === "processed" ? "good" : "neutral"}>{h.stage === "processed" ? "Processed" : "Raw"}</Badge>
                        <ScoreValue score={h.score} className="w-12 text-right" />
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
              <LinkButton to={`/pipelines/new?dataset=${ds.id}`} variant="primary">Clean this dataset with a pipeline</LinkButton>
            </div>
          </div>
          <Section title="Methodology" className="mt-4"><Methodology /></Section>
        </>
      )}
    </>
  );
}
