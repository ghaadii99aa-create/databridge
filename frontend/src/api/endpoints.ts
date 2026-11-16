import { buildUrl, http, uploadWithProgress } from "./client";
import type {
  Agg, AnalystAnswer, AnalystStatus, Assessment, CategoryData, Comparison, ComparisonData, Dataset, DatasetDetail,
  DistributionData, Filter, Methodology, Overview, Pipeline, QualityBrief, Report, ReportKind, RowsPage, RulesInfo,
  RunBrief, RunDetail, SourceItem, StatsResponse, Suitability, TimeseriesData, TransformConfig, UploadLimits,
} from "./types";

export const api = {
  overview: () => http.get<Overview>("/overview"),

  datasets: {
    list: (search?: string) => http.get<Dataset[]>("/datasets", { search }),
    get: (id: number) => http.get<DatasetDetail>(`/datasets/${id}`),
    limits: () => http.get<UploadLimits>("/datasets/limits"),
    upload: (file: File, name: string | undefined, onProgress: (r: number) => void) => {
      const form = new FormData();
      form.append("file", file);
      if (name) form.append("name", name);
      return uploadWithProgress<DatasetDetail>("/datasets", form, onProgress);
    },
    loadSample: () => http.post<DatasetDetail>("/datasets/sample"),
    rename: (id: number, name: string, description: string | null) =>
      http.patch<DatasetDetail>(`/datasets/${id}`, { name, description }),
    remove: (id: number) => http.del(`/datasets/${id}`),
    preview: (id: number, limit = 50) =>
      http.get<{ columns: { key: string; name: string; type: string }[]; rows: Record<string, string>[]; total_rows: number }>(
        `/datasets/${id}/preview`, { limit }),
    downloadUrl: (id: number) => buildUrl(`/datasets/${id}/download`),
  },

  quality: {
    latest: (datasetId: number) => http.get<Assessment | null>(`/datasets/${datasetId}/quality`),
    run: (datasetId: number) => http.post<Assessment>(`/datasets/${datasetId}/quality`),
    history: (datasetId: number) => http.get<QualityBrief[]>(`/datasets/${datasetId}/quality/history`),
    assessment: (id: number) => http.get<Assessment>(`/quality/assessments/${id}`),
    methodology: () => http.get<Methodology>("/quality/methodology"),
  },

  pipelines: {
    rules: () => http.get<RulesInfo>("/pipelines/rules"),
    list: () => http.get<Pipeline[]>("/pipelines"),
    get: (id: number) => http.get<Pipeline>(`/pipelines/${id}`),
    create: (body: { dataset_id: number; name: string; description?: string | null; config: TransformConfig }) =>
      http.post<Pipeline>("/pipelines", body),
    update: (id: number, body: { name: string; description?: string | null; config: TransformConfig }) =>
      http.put<Pipeline>(`/pipelines/${id}`, body),
    remove: (id: number) => http.del(`/pipelines/${id}`),
    start: (id: number) => http.post<RunBrief>(`/pipelines/${id}/runs`),
    runs: (pipelineId?: number) => http.get<RunBrief[]>("/runs", { pipeline_id: pipelineId }),
    run: (id: number) => http.get<RunDetail>(`/runs/${id}`),
    comparison: (id: number) => http.get<Comparison>(`/runs/${id}/comparison`),
  },

  explorer: {
    sources: () => http.get<SourceItem[]>("/explorer/sources"),
    rows: (q: { source: string; page: number; page_size: number; search?: string; sort?: string;
               order?: "asc" | "desc"; filters?: Filter[] }) =>
      http.get<RowsPage>("/explorer/rows", {
        ...q, filters: q.filters && q.filters.length ? JSON.stringify(q.filters) : undefined,
      }),
    stats: (source: string) => http.get<StatsResponse>("/explorer/stats", { source }),
    exportUrl: (source: string) => buildUrl("/explorer/export", { source }),
  },

  analytics: {
    suitability: (source: string) => http.get<Suitability>("/analytics/suitability", { source }),
    distribution: (source: string, column: string) =>
      http.get<DistributionData>("/analytics/distribution", { source, column }),
    category: (source: string, column: string, measure?: string, agg: Agg = "count") =>
      http.get<CategoryData>("/analytics/category", { source, column, measure, agg }),
    timeseries: (source: string, column: string, measure?: string, agg: Agg = "count") =>
      http.get<TimeseriesData>("/analytics/timeseries", { source, column, measure, agg }),
    comparison: (source: string, column: string, split: string, measure?: string, agg: Agg = "count") =>
      http.get<ComparisonData>("/analytics/comparison", { source, column, split, measure, agg }),
  },

  analyst: {
    status: () => http.get<AnalystStatus>("/analyst/status"),
    ask: (source: string, question: string) => http.post<AnalystAnswer>("/analyst/ask", { source, question }),
  },

  reports: {
    list: () => http.get<Report[]>("/reports"),
    create: (body: { kind: ReportKind; format: "pdf" | "csv"; dataset_id?: number; run_id?: number }) =>
      http.post<Report>("/reports", body),
    remove: (id: number) => http.del(`/reports/${id}`),
    downloadUrl: (id: number) => buildUrl(`/reports/${id}/download`),
  },

  health: () => http.get<{ status: string; database: { status: string; engine: string } }>("/health/ready"),
};
