// Types mirror the backend Pydantic schemas (backend/app/schemas) and service return shapes.

export type ColumnType =
  | "integer" | "decimal" | "boolean" | "datetime" | "category" | "identifier" | "text" | "empty";
export type DatasetStatus = "processing" | "ready" | "failed";
export type RunStatus = "pending" | "running" | "succeeded" | "failed";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Dimension = "completeness" | "validity" | "uniqueness" | "consistency";

export interface QualityBrief {
  id: number; stage: "raw" | "processed"; score: number; total_issues: number;
  affected_rows: number; created_at: string;
}

export interface DatasetColumn {
  id: number; position: number; name: string; key: string; inferred_type: ColumnType;
  null_count: number; distinct_count: number; sample_values: string[];
}

export interface Dataset {
  id: number; name: string; description: string | null; original_filename: string;
  file_format: "csv" | "xlsx"; file_size_bytes: number; sha256: string; sheet_name: string | null;
  encoding: string | null; delimiter: string | null; row_count: number; column_count: number;
  status: DatasetStatus; error_message: string | null; is_sample: boolean; ingest_duration_ms: number | null;
  created_at: string; updated_at: string; latest_quality: QualityBrief | null; pipeline_count: number;
  read_only?: boolean;
}
export interface DatasetDetail extends Dataset { columns: DatasetColumn[] }

export interface QualityIssue {
  id: number; check_code: string; dimension: Dimension | "info"; severity: Severity;
  column_key: string | null; column_name: string | null; affected_rows: number; affected_ratio: number;
  message: string; recommendation: string; examples: string[];
}

export interface Assessment {
  id: number; dataset_id: number; run_id: number | null; stage: "raw" | "processed";
  score: number; completeness: number; uniqueness: number; validity: number; consistency: number;
  row_count: number; column_count: number; total_issues: number; affected_rows: number;
  methodology_version: string; created_at: string; issues: QualityIssue[];
  details: {
    counts: Record<string, number>;
    columns: { key: string; name: string; type: ColumnType; missing: number; invalid: number; inconsistent: number }[];
  };
}

export interface Methodology {
  version: string; weights: Record<Dimension, number>; formula: string;
  dimensions: Record<Dimension, string>;
  checks: Record<string, { dimension: string; title: string; rule: string }>;
  type_threshold: number;
}

export interface TransformConfig {
  drop_empty_columns: boolean; trim_whitespace: boolean; normalize_categories: boolean;
  remove_duplicates: boolean; coerce_types: boolean; reject_negative_values: boolean;
  missing_values: "keep" | "drop_rows" | "fill"; numeric_fill: "none" | "median" | "zero";
  required_columns: string[]; type_overrides: Record<string, ColumnType>;
}

export interface RunBrief {
  id: number; pipeline_id: number; status: RunStatus; current_stage: string | null;
  rows_extracted: number | null; rows_loaded: number | null; rows_rejected: number | null;
  error_stage: string | null; error_message: string | null; created_at: string;
  started_at: string | null; finished_at: string | null; duration_ms: number | null;
}

export interface Pipeline {
  id: number; dataset_id: number; dataset_name: string; name: string; description: string | null;
  config: TransformConfig; created_at: string; updated_at: string; last_run: RunBrief | null; run_count: number;
  read_only?: boolean;
}

export interface RunLog {
  id: number; stage: string; level: "debug" | "info" | "warning" | "error"; message: string;
  context: Record<string, unknown> | null; created_at: string;
}

export interface RunDetail extends RunBrief {
  pipeline_name: string; dataset_id: number; dataset_name: string; config_snapshot: TransformConfig;
  stage_timings_ms: Record<string, number>; logs: RunLog[];
  output: { table_name: string; row_count: number; column_count: number; columns: SourceColumn[] } | null;
  quality_before: Assessment | null; quality_after: Assessment | null;
  read_only?: boolean;
}

export interface RulesInfo {
  rules: { key: string; label: string; description: string }[];
  defaults: TransformConfig;
  stages: { key: string; label: string }[];
}

export interface SourceColumn { key: string; name: string; type: ColumnType }
export interface SourceMeta {
  id: string; kind: "raw" | "processed"; label: string; dataset_id: number; dataset_name: string;
  run_id: number | null; row_count: number; columns: SourceColumn[];
}
export interface SourceItem {
  id: string; kind: "raw" | "processed"; dataset_id: number; dataset_name: string; label: string;
  row_count: number; column_count: number; run_id: number | null; created_at: string; is_sample: boolean;
}

export type Row = Record<string, string | number | boolean | null>;
export interface RowsPage { source: SourceMeta; rows: Row[]; page: number; page_size: number; total: number; pages: number }

export type FilterOp = "eq" | "neq" | "contains" | "gt" | "gte" | "lt" | "lte" | "is_null" | "not_null";
export interface Filter { column: string; op: FilterOp; value?: string }

export interface ColumnStat {
  key: string; name: string; type: ColumnType; count: number; missing: number; missing_ratio: number;
  distinct: number; mean?: number; std?: number; min?: number | string; p25?: number; median?: number;
  p75?: number; max?: number | string; sum?: number; span_days?: number;
  top_values?: { value: string; count: number }[];
}
export interface StatsResponse { source: SourceMeta; columns: ColumnStat[] }

export interface Comparison {
  run_id: number; raw_rows: number; processed_rows: number;
  columns: { key: string; name: string; raw_type: ColumnType; processed_type: ColumnType | null; raw_missing: number;
    processed_missing: number | null; raw_distinct: number; processed_distinct: number | null; dropped: boolean }[];
}

export interface Suitability {
  source: SourceMeta;
  numeric_columns: SourceColumn[]; datetime_columns: SourceColumn[]; category_columns: (SourceColumn & { distinct: number })[];
  charts: Record<"distribution" | "category" | "timeseries" | "comparison", { available: boolean; reason: string }>;
}
export type Agg = "count" | "sum" | "mean" | "median";
export interface DistributionData {
  column: SourceColumn; count: number; bins: { start: number; end: number; count: number }[];
  stats: { mean: number; median: number; min: number; max: number; std: number }; note: string | null;
}
export interface CategoryData {
  column: SourceColumn; measure: string | null; agg: Agg; items: { label: string; value: number }[];
  total: number | null; distinct: number;
}
export interface TimeseriesData {
  column: SourceColumn; measure: string | null; agg: Agg; freq: "D" | "W" | "M" | "Q";
  points: { period: string; value: number | null }[]; start: string; end: string;
}
export interface ComparisonData {
  column: SourceColumn; split: SourceColumn; measure: string | null; agg: Agg; series: string[];
  rows: ({ label: string } & Record<string, number | string>)[];
}

export interface AnalystStatus { configured: boolean; provider: string | null; model: string | null; message: string }
export interface AnalystAnswer {
  question: string;
  statistical: { label: string; findings: { title: string; detail: string }[] };
  ai: { label: string; text: string | null; model: string; error: string | null;
        usage: { input_tokens: number | null; output_tokens: number | null } | null } | null;
  ai_status: AnalystStatus;
  shared_profile: Record<string, unknown> | null;
}

export type ReportKind = "dataset_summary" | "quality" | "pipeline_run";
export interface Report {
  id: number; kind: ReportKind; format: "pdf" | "csv"; title: string; dataset_id: number | null;
  run_id: number | null; size_bytes: number; created_at: string;
  read_only?: boolean;
}

export interface Overview {
  datasets: { total: number; ready: number; failed: number };
  records: { ingested: number; processed: number; loaded: number };
  runs: { total: number; succeeded: number; failed: number; active: number };
  pipelines: number; reports: number;
  quality: { score: number | null; datasets_assessed: number; basis: string };
  quality_trend: { id: number; at: string; score: number; stage: "raw" | "processed"; dataset: string }[];
  recent_runs: { id: number; status: RunStatus; created_at: string; duration_ms: number | null; rows_loaded: number | null;
                 rows_rejected: number | null; pipeline_name: string; pipeline_id: number }[];
  latest_datasets: { id: number; name: string; status: DatasetStatus; row_count: number; column_count: number;
                     created_at: string; is_sample: boolean; file_format: string }[];
  activity: { type: "dataset" | "run" | "report"; status: string; at: string; text: string; ref: number }[];
}

export interface UploadLimits {
  max_upload_mb: number; max_rows: number; max_columns: number; allowed_extensions: string[];
  demo_mode?: boolean; retention_hours?: number | null;
  max_datasets_per_visitor?: number | null; max_pipelines_per_visitor?: number | null;
}
