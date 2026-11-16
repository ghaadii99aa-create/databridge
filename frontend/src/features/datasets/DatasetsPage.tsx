import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/endpoints";
import { ScoreValue } from "@/components/ui/QualityBar";
import { EmptyState, ErrorState, LoadingBlock, PageHeader, SampleTag, Section, StatusBadge } from "@/components/ui/primitives";
import { fmtBytes, fmtDate, fmtInt } from "@/lib/format";
import { UploadPanel } from "./UploadPanel";

export default function DatasetsPage() {
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["datasets", q], queryFn: () => api.datasets.list(q || undefined) });

  return (
    <>
      <PageHeader title="Datasets" description="Upload files, check how they were read, and manage what is stored." />
      <Section title="Add a dataset" description="Files are checked by extension and content, stored unchanged, then parsed and profiled.">
        <UploadPanel />
      </Section>

      <Section title="All datasets" actions={
        <div className="relative w-64 max-w-full">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" aria-hidden />
          <input className="field pl-8" placeholder="Search by name" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search datasets" />
        </div>}>
        {isLoading && <LoadingBlock />}
        {error && <ErrorState error={error} onRetry={refetch} />}
        {data && data.length === 0 && (
          <EmptyState title={q ? `No dataset matches "${q}"` : "No datasets yet"}>
            {q ? "Try a different name." : "Upload a file above, or load the sample dataset to see the full workflow."}
          </EmptyState>
        )}
        {data && data.length > 0 && (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-ink/80 text-left text-ink-muted">
                  <th className="px-5 py-2.5 font-medium">Name</th>
                  <th className="py-2.5 font-medium">Status</th>
                  <th className="py-2.5 text-right font-medium">Rows</th>
                  <th className="py-2.5 text-right font-medium">Columns</th>
                  <th className="py-2.5 text-right font-medium">Size</th>
                  <th className="py-2.5 text-right font-medium">Quality</th>
                  <th className="px-5 py-2.5 text-right font-medium">Added</th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id} className="border-b border-stone last:border-0 hover:bg-paper">
                    <td className="max-w-[320px] px-5 py-3">
                      <div className="flex items-center gap-2">
                        <Link to={`/datasets/${d.id}`} className="truncate font-medium text-ink hover:text-forest-deep">{d.name}</Link>
                        {d.is_sample && <SampleTag />}
                      </div>
                      <div className="truncate text-xs text-ink-muted">{d.original_filename}</div>
                    </td>
                    <td className="py-3">
                      <StatusBadge status={d.status} />
                      {d.status === "failed" && <div className="mt-1 max-w-[220px] truncate text-xs text-clay-deep" title={d.error_message ?? ""}>{d.error_message}</div>}
                    </td>
                    <td className="num py-3 text-right">{d.status === "ready" ? fmtInt(d.row_count) : "—"}</td>
                    <td className="num py-3 text-right">{d.status === "ready" ? d.column_count : "—"}</td>
                    <td className="num py-3 text-right text-ink-muted">{fmtBytes(d.file_size_bytes)}</td>
                    <td className="py-3 text-right"><ScoreValue score={d.latest_quality?.score} /></td>
                    <td className="px-5 py-3 text-right text-ink-muted">{fmtDate(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}
