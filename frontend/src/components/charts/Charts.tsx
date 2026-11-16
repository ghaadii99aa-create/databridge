import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { fmtCompact, fmtNum } from "@/lib/format";

/** Categorical order validated for colour-vision deficiency (see docs/DESIGN_SYSTEM.md). Fixed, never cycled. */
export const SERIES = ["#2F7F47", "#8C4F86", "#B8623C", "#3366AE", "#A9851C", "#00897B"];
export const SINGLE = "#526B58";
const AXIS = { fontSize: 11, fill: "#6B6F68" };
const GRID = "#ECEAE3";

export { ChartFrame } from "./ChartFrame";

function TooltipBox({ title, rows }: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded border border-stone-line bg-surface px-3 py-2 text-sm shadow-pop">
      <div className="mb-1 font-medium text-ink">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-ink-soft">
          {r.color && <span className="h-2 w-2 rounded-[2px]" style={{ background: r.color }} />}
          <span className="flex-1">{r.label}</span>
          <span className="num font-medium text-ink">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export function HBarChart({ data, valueLabel }: { data: { label: string; value: number }[]; valueLabel: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, bottom: 0, left: 0 }} barCategoryGap={4}>
        <CartesianGrid horizontal={false} stroke={GRID} />
        <XAxis type="number" tick={AXIS} tickFormatter={fmtCompact} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="label" tick={{ ...AXIS, fill: "#4A4F49" }} width={130} axisLine={false} tickLine={false} />
        <Tooltip cursor={{ fill: "#F1EFE9" }} content={({ active, payload }) => active && payload?.length ? (
          <TooltipBox title={String(payload[0].payload.label)} rows={[{ label: valueLabel, value: fmtNum(payload[0].value as number) }]} />
        ) : null} />
        <Bar isAnimationActive={false} dataKey="value" fill={SINGLE} radius={[0, 4, 4, 0]} maxBarSize={22}
          label={{ position: "right", fontSize: 11, fill: "#4A4F49", formatter: (v: number) => fmtCompact(v) }} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Histogram({ bins, valueName }: { bins: { start: number; end: number; count: number }[]; valueName: string }) {
  // whole-number bins (width 1, centred on integers) are labelled by their integer
  const data = bins.map((b) => ({ ...b, label: b.end - b.start === 1 && Number.isInteger(b.start + 0.5) ? String(b.start + 0.5) : fmtCompact(b.start) }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -8 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="label" tick={AXIS} axisLine={{ stroke: "#CFCBC0" }} tickLine={false} interval="preserveStartEnd" minTickGap={18} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={fmtCompact} />
        <Tooltip cursor={{ fill: "#F1EFE9" }} content={({ active, payload }) => {
          if (!active || !payload?.length) return null;
          const p = payload[0].payload as { start: number; end: number; count: number };
          return <TooltipBox title={`${valueName}: ${fmtNum(p.start)} – ${fmtNum(p.end)}`} rows={[{ label: "Rows", value: fmtNum(p.count) }]} />;
        }} />
        <Bar isAnimationActive={false} dataKey="count" fill={SINGLE} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function TrendLine({ data, valueLabel, domain }: {
  data: { period: string; value: number | null }[]; valueLabel: string; domain?: [number, number];
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="period" tick={AXIS} axisLine={{ stroke: "#CFCBC0" }} tickLine={false} minTickGap={24} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={fmtCompact} domain={domain ?? ["auto", "auto"]} />
        <Tooltip cursor={{ stroke: "#8D918A", strokeDasharray: "3 3" }} content={({ active, payload, label }) => active && payload?.length ? (
          <TooltipBox title={String(label)} rows={[{ label: valueLabel, value: fmtNum(payload[0].value as number) }]} />
        ) : null} />
        <Line isAnimationActive={false} type="linear" dataKey="value" stroke={SINGLE} strokeWidth={2} dot={data.length <= 24 ? { r: 3, fill: SINGLE, strokeWidth: 0 } : false}
          activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }} connectNulls={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ rows, series }: { rows: Record<string, string | number>[]; series: string[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -8 }} barCategoryGap="18%" barGap={2}>
        <CartesianGrid vertical={false} stroke={GRID} />
        <XAxis dataKey="label" tick={AXIS} axisLine={{ stroke: "#CFCBC0" }} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={fmtCompact} />
        <Tooltip cursor={{ fill: "#F1EFE9" }} content={({ active, payload, label }) => active && payload?.length ? (
          <TooltipBox title={String(label)} rows={payload.map((p) => ({ label: String(p.name), value: fmtNum(p.value as number), color: p.color }))} />
        ) : null} />
        <Legend iconType="square" iconSize={9} wrapperStyle={{ fontSize: 12, color: "#4A4F49", paddingTop: 8 }} />
        {series.map((s, i) => (
          <Bar isAnimationActive={false} key={s} dataKey={s} name={s} fill={SERIES[i % SERIES.length]} radius={[3, 3, 0, 0]} maxBarSize={28} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
