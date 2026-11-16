import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { api } from "@/api/endpoints";
import { useToast } from "@/components/ui/overlays";
import { Button } from "@/components/ui/primitives";
import { fmtBytes } from "@/lib/format";
import { errorMessage, useLoadSample } from "@/lib/hooks";

export function validateFile(file: File, maxMb: number, allowed: string[]): string | null {
  const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
  const schema = z.object({
    ext: z.string().refine((e) => allowed.includes(e), { message: `Only ${allowed.join(" and ")} files can be uploaded.` }),
    size: z.number().positive("The file is empty.").max(maxMb * 1024 * 1024, `The file is larger than the ${maxMb} MB limit.`),
  });
  const r = schema.safeParse({ ext, size: file.size });
  return r.success ? null : r.error.issues[0].message;
}

export function UploadPanel() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const sample = useLoadSample();
  const { data: limits } = useQuery({ queryKey: ["limits"], queryFn: api.datasets.limits, staleTime: Infinity });
  const maxMb = limits?.max_upload_mb ?? 50;
  const allowed = limits?.allowed_extensions ?? [".csv", ".xlsx"];

  const upload = useMutation({
    mutationFn: () => api.datasets.upload(file!, name.trim() || undefined, setProgress),
    onSuccess: (ds) => {
      qc.invalidateQueries();
      if (ds.status === "failed") {
        setError(`The file was received but could not be processed: ${ds.error_message}`);
        return;
      }
      toast("success", `Ingested "${ds.name}" — ${ds.row_count.toLocaleString()} rows, ${ds.column_count} columns`);
      navigate(`/datasets/${ds.id}`);
    },
    onError: (e) => setError(errorMessage(e)),
    onSettled: () => setProgress(0),
  });

  const pick = (f: File | undefined) => {
    if (!f) return;
    const problem = validateFile(f, maxMb, allowed);
    setError(problem);
    setFile(problem ? null : f);
    if (!problem && !name) setName(f.name.replace(/\.[^.]+$/, ""));
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  };

  return (
    <div className="panel grid gap-0 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx("m-3 flex min-h-[176px] flex-col items-center justify-center rounded border border-dashed px-6 py-6 text-center transition-colors",
          dragging ? "border-forest bg-sage-soft" : "border-stone-dark bg-paper")}
      >
        {file ? (
          <div className="flex items-center gap-3 text-left">
            <FileSpreadsheet className="h-8 w-8 text-forest" aria-hidden />
            <div>
              <div className="font-medium text-ink">{file.name}</div>
              <div className="text-sm text-ink-muted">{fmtBytes(file.size)}</div>
              <button className="link mt-1 text-sm" onClick={() => { setFile(null); setName(""); }} disabled={upload.isPending}>Choose another file</button>
            </div>
          </div>
        ) : (
          <>
            <UploadCloud className="h-7 w-7 text-ink-muted" aria-hidden />
            <p className="mt-2 text-base text-ink">Drop a CSV or Excel file here</p>
            <p className="text-sm text-ink-muted">Up to {maxMb} MB{limits ? ` and ${limits.max_rows.toLocaleString()} rows` : ""}. The first sheet with data is used for Excel files.</p>
            <Button size="sm" className="mt-3" onClick={() => input.current?.click()}>Browse files</Button>
          </>
        )}
        <input ref={input} type="file" accept={allowed.join(",")} className="hidden"
          onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} aria-label="Choose a file to upload" />
      </div>

      <div className="flex flex-col justify-between gap-4 border-t border-stone-line p-5 md:border-l md:border-t-0">
        <div>
          <label htmlFor="ds-name" className="label">Dataset name</label>
          <input id="ds-name" className="field" value={name} maxLength={200} onChange={(e) => setName(e.target.value)}
            placeholder="Defaults to the file name" disabled={upload.isPending} />
          {error && <p role="alert" className="mt-2 text-sm text-clay-deep">{error}</p>}
          {upload.isPending && (
            <div className="mt-3">
              <div className="h-1.5 overflow-hidden rounded-full bg-stone">
                <div className="h-full bg-forest transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
              <p className="mt-1.5 text-xs text-ink-muted">
                {progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : "Validating, profiling and staging rows…"}
              </p>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" disabled={!file} loading={upload.isPending} onClick={() => { setError(null); upload.mutate(); }}>
            Upload and profile
          </Button>
          <span className="text-sm text-ink-muted">or</span>
          <Button variant="ghost" onClick={() => sample.mutate()} loading={sample.isPending}>Load sample dataset</Button>
        </div>
      </div>
    </div>
  );
}
