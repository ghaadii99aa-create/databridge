import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, XCircle } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "@/api/client";

/* ---------- Button ---------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-forest text-white hover:bg-forest-deep border border-forest-deep/40",
  secondary: "bg-surface text-ink border border-stone-dark hover:border-ink-faint hover:bg-paper",
  ghost: "text-ink-soft hover:bg-stone/70 hover:text-ink border border-transparent",
  danger: "bg-clay-deep text-white hover:bg-[#6E3F2D] border border-clay-deep",
};

export function buttonClasses(variant: Variant = "secondary", size: "sm" | "md" = "md", extra?: string) {
  return clsx(
    "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-55",
    size === "sm" ? "h-8 px-2.5 text-sm" : "h-9 px-3.5 text-base",
    VARIANTS[variant], extra,
  );
}

/** A link that looks like a button (navigation stays a real <a>). */
export function LinkButton({ to, href, variant, size, icon, children, download }: {
  to?: string; href?: string; variant?: Variant; size?: "sm" | "md"; icon?: ReactNode; children: ReactNode; download?: boolean;
}) {
  if (href) return <a href={href} download={download} className={buttonClasses(variant, size)}>{icon}{children}</a>;
  return <Link to={to ?? "/"} className={buttonClasses(variant, size)}>{icon}{children}</Link>;
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }, ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={buttonClasses(variant, size, className)}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

/* ---------- Status badge ---------- */

type Tone = "good" | "warn" | "bad" | "neutral" | "active";
const TONES: Record<Tone, string> = {
  good: "bg-sage text-forest-deep",
  warn: "bg-amber-soft text-[#7A5F10]",
  bad: "bg-clay-soft text-clay-deep",
  neutral: "bg-stone text-ink-soft",
  active: "bg-[#E4EAF2] text-[#38557A]",
};
const STATUS_TONE: Record<string, Tone> = {
  ready: "good", succeeded: "good", failed: "bad", processing: "active", running: "active", pending: "neutral",
};
const STATUS_ICON: Record<Tone, ReactNode> = {
  good: <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />,
  bad: <XCircle className="h-3.5 w-3.5" aria-hidden />,
  active: <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />,
  neutral: <CircleDashed className="h-3.5 w-3.5" aria-hidden />,
  warn: <AlertTriangle className="h-3.5 w-3.5" aria-hidden />,
};

export function Badge({ tone = "neutral", children, icon, className }: { tone?: Tone; children: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex h-6 items-center gap-1 rounded-sm px-2 text-xs font-medium", TONES[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "neutral";
  return <Badge tone={tone} icon={STATUS_ICON[tone]}>{status.charAt(0).toUpperCase() + status.slice(1)}</Badge>;
}

export function SampleTag() {
  return <Badge tone="warn" className="h-5 px-1.5 text-2xs">Sample data</Badge>;
}

/* ---------- Layout pieces ---------- */

export function PageHeader({ title, description, actions, meta }: {
  title: string; description?: ReactNode; actions?: ReactNode; meta?: ReactNode;
}) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-4 border-b border-stone-line pb-5">
      <div className="min-w-0 max-w-3xl">
        {meta && <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-ink-muted">{meta}</div>}
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-base text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Section({ title, description, actions, children, className }: {
  title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={clsx("mb-9", className)}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-md font-semibold text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-ink-muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Panel({ children, className, padded = true }: { children: ReactNode; className?: string; padded?: boolean }) {
  return <div className={clsx("panel", padded && "p-5", className)}>{children}</div>;
}

/** A labelled figure. Used in place of decorative KPI cards. */
export function Figure({ label, value, detail, tone }: { label: string; value: ReactNode; detail?: ReactNode; tone?: "bad" }) {
  return (
    <div className="min-w-0">
      <div className="text-sm text-ink-muted">{label}</div>
      <div className={clsx("num mt-1 text-xl font-semibold", tone === "bad" ? "text-clay-deep" : "text-ink")}>{value}</div>
      {detail && <div className="mt-0.5 text-xs text-ink-muted">{detail}</div>}
    </div>
  );
}

/* ---------- States ---------- */

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-md border border-dashed border-stone-dark bg-surface/60 px-6 py-8">
      {icon && <div className="text-forest">{icon}</div>}
      <div className="max-w-xl">
        <h3 className="text-md font-semibold text-ink">{title}</h3>
        {children && <div className="mt-1 text-base text-ink-muted">{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-clay/40 bg-clay-soft/60 px-4 py-3">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-clay-deep" aria-hidden />
      <div className="min-w-0 flex-1 text-base">
        <p className="font-medium text-ink">{e?.message ?? "Something went wrong while loading this view."}</p>
        {e?.requestId && <p className="mt-0.5 text-xs text-ink-muted">Request ID {e.requestId}</p>}
      </div>
      {onRetry && <Button size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  return (
    <div className={clsx("flex items-start gap-2.5 rounded-md border px-4 py-3 text-base",
      tone === "warn" ? "border-amber/40 bg-amber-soft/70" : "border-stone-line bg-sage-soft")}>
      {tone === "warn"
        ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" aria-hidden />
        : <Info className="mt-0.5 h-4 w-4 shrink-0 text-forest" aria-hidden />}
      <div className="min-w-0 text-ink-soft">{children}</div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded bg-stone", className)} aria-hidden />;
}

export function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={clsx("h-4", i % 3 === 2 ? "w-2/3" : "w-full")} />)}
    </div>
  );
}

/* ---------- Form controls ---------- */

export function Select({ label, value, onChange, options, className, hint, id }: {
  label?: string; value: string; onChange: (v: string) => void; hint?: string; id?: string;
  options: { value: string; label: string; disabled?: boolean }[]; className?: string;
}) {
  const sid = id ?? `sel-${label?.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div className={className}>
      {label && <label htmlFor={sid} className="label">{label}</label>}
      <select id={sid} className="field pr-8" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
      </select>
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}

export function Toggle({ checked, onChange, label, description, id }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; id: string;
}) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-start gap-3 py-2.5">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded-sm border-stone-dark accent-forest" />
      <span className="min-w-0">
        <span className="block text-base font-medium text-ink">{label}</span>
        {description && <span className="block text-sm text-ink-muted">{description}</span>}
      </span>
    </label>
  );
}
