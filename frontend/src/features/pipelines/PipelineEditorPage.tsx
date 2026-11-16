import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { api } from "@/api/endpoints";
import type { ColumnType, TransformConfig } from "@/api/types";
import { useToast } from "@/components/ui/overlays";
import { Button, ErrorState, LoadingBlock, PageHeader, Panel, Section, Select, Toggle } from "@/components/ui/primitives";
import { TYPE_LABEL } from "@/lib/format";
import { errorMessage } from "@/lib/hooks";

export const pipelineSchema = z.object({
  dataset_id: z.number({ invalid_type_error: "Choose a source dataset." }).int().positive("Choose a source dataset."),
  name: z.string().trim().min(1, "Give the pipeline a name.").max(200, "Use 200 characters or fewer."),
  description: z.string().max(2000).optional(),
});

const BOOL_RULES: (keyof TransformConfig)[] = [
  "drop_empty_columns", "trim_whitespace", "normalize_categories", "remove_duplicates", "coerce_types", "reject_negative_values",
];
const OVERRIDE_TYPES: ColumnType[] = ["integer", "decimal", "boolean", "datetime", "category", "text", "identifier"];

export default function PipelineEditorPage() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const { data: rules } = useQuery({ queryKey: ["rules"], queryFn: api.pipelines.rules, staleTime: Infinity });
  const { data: datasets } = useQuery({ queryKey: ["datasets", ""], queryFn: () => api.datasets.list() });
  const { data: existing, isLoading: loadingExisting, error } = useQuery({
    queryKey: ["pipeline", editId], queryFn: () => api.pipelines.get(editId!), enabled: !!editId,
  });

  const [datasetId, setDatasetId] = useState<number>(Number(params.get("dataset")) || 0);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [config, setConfig] = useState<TransformConfig | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => { if (rules && !config && !editId) setConfig(rules.defaults); }, [rules, config, editId]);
  useEffect(() => {
    if (existing) {
      setDatasetId(existing.dataset_id); setName(existing.name);
      setDescription(existing.description ?? ""); setConfig(existing.config);
    }
  }, [existing]);
  const ready = (datasets ?? []).filter((d) => d.status === "ready");
  useEffect(() => { if (!datasetId && ready[0] && !editId) setDatasetId(ready[0].id); }, [ready, datasetId, editId]);
  useEffect(() => {
    const ds = ready.find((d) => d.id === datasetId);
    if (ds && !name && !editId) setName(`Clean ${ds.name}`);
  }, [datasetId, ready, name, editId]);

  const { data: dataset } = useQuery({ queryKey: ["dataset", datasetId], queryFn: () => api.datasets.get(datasetId), enabled: !!datasetId });
  const ruleInfo = useMemo(() => Object.fromEntries((rules?.rules ?? []).map((r) => [r.key, r])), [rules]);

  const save = useMutation({
    mutationFn: async (run: boolean) => {
      const body = { name: name.trim(), description: description.trim() || null, config: config! };
      const p = editId ? await api.pipelines.update(editId, body) : await api.pipelines.create({ dataset_id: datasetId, ...body });
      return { p, run: run ? await api.pipelines.start(p.id) : null };
    },
    onSuccess: ({ p, run }) => {
      qc.invalidateQueries();
      toast("success", editId ? "Pipeline saved" : `Pipeline "${p.name}" created`);
      navigate(run ? `/runs/${run.id}` : "/pipelines");
    },
    onError: (e) => toast("error", errorMessage(e)),
  });

  const submit = (run: boolean) => {
    const r = pipelineSchema.safeParse({ dataset_id: datasetId, name, description });
    if (!r.success) {
      setErrors(Object.fromEntries(r.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    setErrors({});
    save.mutate(run);
  };

  if (editId && loadingExisting) return <LoadingBlock rows={8} />;
  if (error) return <ErrorState error={error} />;
  if (!config || !rules) return <LoadingBlock rows={8} />;
  const set = <K extends keyof TransformConfig>(k: K, v: TransformConfig[K]) => setConfig({ ...config, [k]: v });

  return (
    <>
      <PageHeader title={editId ? `Edit ${existing?.name ?? "pipeline"}` : "New pipeline"}
        description="Rules run in the order listed. Every change a rule makes is counted and written to the run log." />
      <form className="grid grid-cols-[minmax(0,1fr)] gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]" onSubmit={(e) => { e.preventDefault(); submit(false); }} noValidate>
        <div>
          <Section title="Definition">
            <Panel className="space-y-4">
              <Select label="Source dataset" id="p-dataset" value={String(datasetId || "")} onChange={(v) => setDatasetId(Number(v))}
                options={[{ value: "", label: "Choose a dataset", disabled: true }, ...ready.map((d) => ({ value: String(d.id), label: d.name }))]}
                hint={editId ? "The source of an existing pipeline cannot be changed." : undefined} />
              {errors.dataset_id && <p className="-mt-2 text-sm text-clay-deep" role="alert">{errors.dataset_id}</p>}
              <div>
                <label htmlFor="p-name" className="label">Name</label>
                <input id="p-name" className="field" value={name} onChange={(e) => setName(e.target.value)} maxLength={200}
                  aria-invalid={!!errors.name} aria-describedby={errors.name ? "p-name-err" : undefined} />
                {errors.name && <p id="p-name-err" className="mt-1 text-sm text-clay-deep" role="alert">{errors.name}</p>}
              </div>
              <div>
                <label htmlFor="p-desc" className="label">Description <span className="font-normal text-ink-faint">(optional)</span></label>
                <textarea id="p-desc" className="field h-20 py-2" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
              </div>
            </Panel>
          </Section>

          <Section title="Cleaning rules">
            <Panel className="divide-y divide-stone py-1">
              {BOOL_RULES.map((k) => (
                <Toggle key={k} id={`r-${k}`} checked={config[k] as boolean} onChange={(v) => set(k, v as never)}
                  label={ruleInfo[k]?.label ?? k} description={ruleInfo[k]?.description} />
              ))}
              <div className="grid grid-cols-[minmax(0,1fr)] gap-4 py-3 sm:grid-cols-2">
                <Select label="Missing values" id="r-missing" value={config.missing_values} onChange={(v) => set("missing_values", v as TransformConfig["missing_values"])}
                  options={[{ value: "fill", label: "Fill text with 'Unknown'" }, { value: "keep", label: "Keep empty" }, { value: "drop_rows", label: "Drop incomplete rows" }]} />
                <Select label="Missing numbers" id="r-numeric" value={config.numeric_fill} onChange={(v) => set("numeric_fill", v as TransformConfig["numeric_fill"])}
                  options={[{ value: "none", label: "Leave empty" }, { value: "median", label: "Fill with median" }, { value: "zero", label: "Fill with zero" }]}
                  hint="Applies with the fill strategy. Leaving numbers empty keeps totals accurate." />
              </div>
            </Panel>
          </Section>
        </div>

        <div>
          <Section title="Columns" description="Required columns reject rows where they are empty. Override a type when the inference is wrong.">
            {!dataset ? <LoadingBlock /> : (
              <div className="panel overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-ink/80 text-left text-ink-muted">
                    <th className="px-4 py-2 font-medium">Column</th><th className="py-2 font-medium">Type</th>
                    <th className="px-4 py-2 text-center font-medium">Required</th></tr></thead>
                  <tbody>
                    {dataset.columns.map((c) => {
                      const required = config.required_columns.includes(c.key);
                      return (
                        <tr key={c.key} className="border-b border-stone last:border-0">
                          <td className="px-4 py-1.5"><div className="font-medium">{c.name}</div>
                            <div className="text-xs text-ink-muted">inferred {TYPE_LABEL[c.inferred_type].toLowerCase()}</div></td>
                          <td className="py-1.5">
                            <select aria-label={`Type for ${c.name}`} className="field h-8 w-36 text-sm"
                              value={config.type_overrides[c.key] ?? ""}
                              onChange={(e) => {
                                const o = { ...config.type_overrides };
                                if (e.target.value) o[c.key] = e.target.value as ColumnType; else delete o[c.key];
                                set("type_overrides", o);
                              }}>
                              <option value="">As inferred</option>
                              {OVERRIDE_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
                            </select>
                          </td>
                          <td className="px-4 py-1.5 text-center">
                            <input type="checkbox" className="h-4 w-4 accent-forest" checked={required} aria-label={`${c.name} is required`}
                              onChange={(e) => set("required_columns", e.target.checked
                                ? [...config.required_columns, c.key] : config.required_columns.filter((k) => k !== c.key))} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="primary" loading={save.isPending && save.variables === true} onClick={() => submit(true)}>Save and run</Button>
            <Button type="submit" loading={save.isPending && save.variables === false}>Save</Button>
            <Button type="button" variant="ghost" onClick={() => navigate(-1)}>Cancel</Button>
          </div>
        </div>
      </form>
    </>
  );
}
