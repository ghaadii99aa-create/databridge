import type { ColumnType } from "@/api/types";

const nf = new Intl.NumberFormat("en-US");
const nf2 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const fixed2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const fmtInt = (n: number | null | undefined) => (n == null ? "—" : nf.format(n));
export const fmtNum = (n: number | null | undefined) => (n == null ? "—" : nf2.format(n));
export const fmtCompact = (n: number | null | undefined) => (n == null ? "—" : compact.format(n));
export const fmtPct = (ratio: number, digits = 1) => `${(ratio * 100).toFixed(digits)}%`;

export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function fmtRelative(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return fmtDate(iso, false);
}

export const TYPE_LABEL: Record<ColumnType, string> = {
  integer: "Integer", decimal: "Decimal", boolean: "Boolean", datetime: "Date", category: "Category",
  identifier: "Identifier", text: "Text", empty: "Empty",
};

export function formatCell(value: unknown, type?: ColumnType): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number") return type === "integer" ? nf.format(value) : type === "decimal" ? fixed2.format(value) : nf2.format(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

export function scoreTone(score: number | null | undefined): "good" | "fair" | "poor" | "none" {
  if (score == null) return "none";
  if (score >= 97) return "good";
  if (score >= 90) return "fair";
  return "poor";
}
