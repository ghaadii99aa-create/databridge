import clsx from "clsx";

import type { Dimension } from "@/api/types";
import { scoreTone } from "@/lib/format";

/**
 * The weighted quality bar — DataBridge's signature figure.
 * Each segment's width is proportional to the dimension's weight in the score (30/30/20/20); its fill is the
 * dimension's own score. The filled area of the whole bar is therefore the quality score itself,
 * so the figure shows both the result and how it was calculated.
 */
export const DIMENSIONS: { key: Dimension; label: string; weight: number }[] = [
  { key: "completeness", label: "Completeness", weight: 0.3 },
  { key: "validity", label: "Validity", weight: 0.3 },
  { key: "uniqueness", label: "Uniqueness", weight: 0.2 },
  { key: "consistency", label: "Consistency", weight: 0.2 },
];

type Scores = Record<Dimension, number>;

export function QualityBar({ scores, size = "md", showLabels = true }: {
  scores: Scores; size?: "sm" | "md"; showLabels?: boolean;
}) {
  return (
    <div>
      <div className={clsx("flex gap-[2px]", size === "sm" ? "h-2" : "h-3.5")}
        role="img"
        aria-label={DIMENSIONS.map((d) => `${d.label} ${scores[d.key].toFixed(1)} percent`).join(", ")}>
        {DIMENSIONS.map((d) => {
          const v = Math.max(0, Math.min(100, scores[d.key]));
          return (
            <div key={d.key} className="relative min-w-0 overflow-hidden rounded-[2px] bg-stone" style={{ flexGrow: d.weight, flexShrink: 1, flexBasis: 0 }}
              title={`${d.label}: ${v.toFixed(2)}% (weight ${d.weight * 100}%)`}>
              <div className={clsx("h-full", v >= 97 ? "bg-forest" : v >= 90 ? "bg-forest-light" : "bg-clay")}
                style={{ width: `${v}%` }} />
            </div>
          );
        })}
      </div>
      {showLabels && (
        <div className="mt-2 flex gap-[2px]">
          {DIMENSIONS.map((d) => (
            <div key={d.key} className="min-w-0" style={{ flexGrow: d.weight, flexShrink: 1, flexBasis: 0 }}>
              <div className="truncate text-xs text-ink-muted">{d.label} ({d.weight * 100}%)</div>
              <div className="num text-base font-medium text-ink">{scores[d.key].toFixed(1)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ScoreValue({ score, className }: { score: number | null | undefined; className?: string }) {
  const tone = scoreTone(score);
  return (
    <span className={clsx("num font-semibold",
      tone === "poor" ? "text-clay-deep" : tone === "fair" ? "text-ink" : tone === "good" ? "text-forest-deep" : "text-ink-faint",
      className)}>
      {score == null ? "—" : score.toFixed(1)}
    </span>
  );
}
