import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "@/api/endpoints";
import type { SourceItem } from "@/api/types";

/** Source selection shared by Explorer, Analytics and the AI analyst. Kept in the URL so views are linkable. */
export function useSource(preferProcessed = true) {
  const [params, setParams] = useSearchParams();
  const { data: sources, isLoading } = useQuery({ queryKey: ["sources"], queryFn: api.explorer.sources });
  const current = params.get("source");
  useEffect(() => {
    if (!current && sources?.length) {
      const pick = (preferProcessed && sources.find((s) => s.kind === "processed")) || sources[0];
      setParams((p) => { p.set("source", pick.id); return p; }, { replace: true });
    }
  }, [current, sources, preferProcessed, setParams]);
  const source = sources?.find((s) => s.id === current) ?? null;
  const setSource = (id: string) => setParams({ source: id });
  return { sources: sources ?? [], source, sourceId: current, setSource, isLoading };
}

export function SourcePicker({ sources, value, onChange, id = "source-picker" }: {
  sources: SourceItem[]; value: string | null; onChange: (id: string) => void; id?: string;
}) {
  const groups = new Map<string, SourceItem[]>();
  sources.forEach((s) => groups.set(s.dataset_name + "|" + s.dataset_id, [...(groups.get(s.dataset_name + "|" + s.dataset_id) ?? []), s]));
  return (
    <div className="w-full sm:w-80">
      <label htmlFor={id} className="sr-only">Data source</label>
      <select id={id} className="field" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {[...groups.entries()].map(([key, items]) => (
          <optgroup key={key} label={key.split("|")[0] + (items[0].is_sample ? " (sample data)" : "")}>
            {items.map((s) => <option key={s.id} value={s.id}>{s.label}, {s.row_count.toLocaleString()} rows</option>)}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
