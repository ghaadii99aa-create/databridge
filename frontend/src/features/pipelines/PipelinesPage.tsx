import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "@/api/endpoints";
import type { Pipeline } from "@/api/types";
import { ConfirmDialog, useToast } from "@/components/ui/overlays";
import {
  Button, EmptyState, ErrorState, LinkButton, LoadingBlock, PageHeader, Section, StatusBadge, SampleTag,
} from "@/components/ui/primitives";
import { fmtDuration, fmtInt, fmtRelative } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";

export function useStartRun() {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (pipelineId: number) => api.pipelines.start(pipelineId),
    onSuccess: (run) => { qc.invalidateQueries(); navigate(`/runs/${run.id}`); },
    onError: (e) => toast("error", errorMessage(e)),
  });
}

export default function PipelinesPage() {
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["pipelines"], queryFn: api.pipelines.list, refetchInterval: 10_000 });
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: () => api.pipelines.runs(), refetchInterval: 10_000 });
  const start = useStartRun();
  const qc = useQueryClient();
  const toast = useToast();
  const [deleting, setDeleting] = useState<Pipeline | null>(null);
  const remove = useMutation({
    mutationFn: (id: number) => api.pipelines.remove(id),
    onSuccess: () => { qc.invalidateQueries(); setDeleting(null); toast("success", "Pipeline deleted"); },
    onError: (e) => toast("error", errorMessage(e)),
  });

  return (
    <>
      <PageHeader title="Pipelines"
        description="Each pipeline extracts a dataset's raw rows, validates them, applies your cleaning rules and loads the result into a new database table."
        actions={<LinkButton to="/pipelines/new" variant="primary" icon={<Plus className="h-4 w-4" />}>New pipeline</LinkButton>} />
      {isLoading && <LoadingBlock />}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {data && data.length === 0 && (
        <EmptyState title="No pipelines yet" action={<LinkButton to="/pipelines/new" variant="primary">Create a pipeline</LinkButton>}>
          A pipeline turns a raw upload into a clean, typed table you can query, chart and report on.
        </EmptyState>
      )}
      {data && data.length > 0 && (
        <Section title="Definitions">
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
                <th className="px-5 py-2.5 font-medium">Pipeline</th><th className="py-2.5 font-medium">Source dataset</th>
                <th className="py-2.5 font-medium">Last run</th><th className="py-2.5 text-right font-medium">Runs</th>
                <th className="px-5 py-2.5 text-right font-medium"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id} className="border-b border-stone last:border-0">
                    <td className="px-5 py-3"><div className="flex items-center gap-2 font-medium">{p.name}{p.read_only && <SampleTag />}</div>
                      {p.description && <div className="max-w-[280px] truncate text-xs text-ink-muted">{p.description}</div>}</td>
                    <td className="py-3"><Link to={`/datasets/${p.dataset_id}`} className="hover:text-forest-deep">{p.dataset_name}</Link></td>
                    <td className="py-3">
                      {p.last_run ? (
                        <Link to={`/runs/${p.last_run.id}`} className="flex items-center gap-2">
                          <StatusBadge status={p.last_run.status} />
                          <span className="text-ink-muted">{fmtRelative(p.last_run.created_at)}</span>
                        </Link>
                      ) : <span className="text-ink-faint">Never run</span>}
                    </td>
                    <td className="num py-3 text-right">{p.run_count}</td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-1.5">
                        {p.read_only ? (
                          <LinkButton to={`/pipelines/new?dataset=${p.dataset_id}`} size="sm" variant="ghost">Make a copy</LinkButton>
                        ) : <>
                          <LinkButton to={`/pipelines/${p.id}/edit`} size="sm" variant="ghost">Edit</LinkButton>
                          <Button size="sm" variant="ghost" onClick={() => setDeleting(p)}>Delete</Button>
                        </>}
                        {!p.read_only && <Button size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />}
                          loading={start.isPending && start.variables === p.id}
                          disabled={p.last_run?.status === "running" || p.last_run?.status === "pending"}
                          onClick={() => start.mutate(p.id)}>Run</Button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {runs && runs.length > 0 && (
        <Section title="Execution history">
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
                <th className="px-5 py-2.5 font-medium">Run</th><th className="py-2.5 font-medium">Status</th>
                <th className="py-2.5 text-right font-medium">Extracted</th><th className="py-2.5 text-right font-medium">Loaded</th>
                <th className="py-2.5 text-right font-medium">Rejected</th><th className="py-2.5 text-right font-medium">Duration</th>
                <th className="px-5 py-2.5 text-right font-medium">Started</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-b border-stone last:border-0 hover:bg-paper">
                    <td className="px-5 py-2.5"><Link to={`/runs/${r.id}`} className="font-medium hover:text-forest-deep">#{r.id} {data?.find((p) => p.id === r.pipeline_id)?.name}</Link></td>
                    <td className="py-2.5"><StatusBadge status={r.status} />{r.error_stage && <span className="ml-2 text-xs text-clay-deep">at {r.error_stage}</span>}</td>
                    <td className="num py-2.5 text-right">{fmtInt(r.rows_extracted)}</td>
                    <td className="num py-2.5 text-right">{fmtInt(r.rows_loaded)}</td>
                    <td className="num py-2.5 text-right">{fmtInt(r.rows_rejected)}</td>
                    <td className="num py-2.5 text-right text-ink-muted">{fmtDuration(r.duration_ms)}</td>
                    <td className="px-5 py-2.5 text-right text-ink-muted">{fmtRelative(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <ConfirmDialog open={!!deleting} title={`Delete "${deleting?.name}"?`} confirmLabel="Delete pipeline" danger
        busy={remove.isPending} onCancel={() => setDeleting(null)} onConfirm={() => deleting && remove.mutate(deleting.id)}>
        Its {deleting?.run_count} run(s), execution logs and processed tables will be removed. The source dataset is not affected.
      </ConfirmDialog>
    </>
  );
}
