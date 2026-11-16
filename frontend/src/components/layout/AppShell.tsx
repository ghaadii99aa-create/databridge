import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  BarChart3, Database, FileText, GitBranch, LayoutGrid, Menu, MessageSquareText, ShieldCheck, Table2, X,
} from "lucide-react";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { api } from "@/api/endpoints";
import { LoadingBlock } from "@/components/ui/primitives";

const NAV: { group: string | null; items: { to: string; label: string; icon: ReactNode }[] }[] = [
  { group: null, items: [{ to: "/", label: "Overview", icon: <LayoutGrid className="h-4 w-4" /> }] },
  {
    group: "Prepare",
    items: [
      { to: "/datasets", label: "Datasets", icon: <Database className="h-4 w-4" /> },
      { to: "/quality", label: "Data quality", icon: <ShieldCheck className="h-4 w-4" /> },
      { to: "/pipelines", label: "Pipelines", icon: <GitBranch className="h-4 w-4" /> },
    ],
  },
  {
    group: "Analyse",
    items: [
      { to: "/explorer", label: "Explorer", icon: <Table2 className="h-4 w-4" /> },
      { to: "/analytics", label: "Analytics", icon: <BarChart3 className="h-4 w-4" /> },
      { to: "/analyst", label: "AI analyst", icon: <MessageSquareText className="h-4 w-4" /> },
    ],
  },
  { group: "Deliver", items: [{ to: "/reports", label: "Reports", icon: <FileText className="h-4 w-4" /> }] },
];

function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="5" fill="#242824" />
        <path d="M7 21h18M7 21v-6M25 21v-6M7 15c3-5 15-5 18 0" stroke="#DCE5DC" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      </svg>
      <span className="text-md font-semibold tracking-tight text-ink">DataBridge</span>
    </div>
  );
}

function ApiStatus() {
  const { data, isError } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000, retry: 0 });
  const ok = data?.database.status === "ok";
  return (
    <div className="flex items-center gap-2 text-xs text-ink-muted" title="Live result of GET /api/health/ready">
      <span className={clsx("h-2 w-2 rounded-full", isError ? "bg-clay" : ok ? "bg-forest" : "bg-stone-dark")} />
      {isError ? "API unreachable" : ok ? `API online (${data?.database.engine})` : "Checking API…"}
    </div>
  );
}

/** Shown only when the server runs in public demo mode (DEMO_MODE=true). */
function DemoNotice() {
  const { data } = useQuery({ queryKey: ["limits"], queryFn: api.datasets.limits, staleTime: Infinity });
  if (!data?.demo_mode) return null;
  return (
    <aside aria-label="About this demo" className="mb-6 rounded-md border border-stone-line bg-sage-soft px-4 py-3 text-sm text-ink-soft">
      <p>
        <span className="font-medium text-ink">Public demo.</span>{" "}
        The retail dataset is synthetic demonstration data, shared and read-only. Files you upload are visible only in
        this browser and are deleted after {data.retention_hours ?? 24} hours.
        Uploads are limited to {data.max_upload_mb} MB and {data.max_rows.toLocaleString()} rows.
      </p>
    </aside>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 py-5">
      {NAV.map((section, i) => (
        <div key={i}>
          {section.group && <div className="mb-1.5 px-2.5 text-xs font-medium text-ink-faint">{section.group}</div>}
          <ul className="space-y-0.5">
            {section.items.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.to === "/"} onClick={onNavigate}
                  className={({ isActive }) => clsx(
                    "flex h-8 items-center gap-2.5 rounded px-2.5 text-base transition-colors",
                    isActive ? "bg-surface font-medium text-ink shadow-[inset_2px_0_0_#526B58]" : "text-ink-soft hover:bg-stone/70 hover:text-ink",
                  )}>
                  <span className="text-ink-muted">{item.icon}</span>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_minmax(0,1fr)] lg:bg-[linear-gradient(to_right,#EEEDE7_231px,#DEDBD2_231px,#DEDBD2_232px,transparent_232px)]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen flex-col lg:flex">
        <div className="flex h-16 items-center px-5"><Wordmark /></div>
        <Nav />
        <div className="border-t border-stone-line px-5 py-4"><ApiStatus /></div>
      </aside>

      <div className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-stone-line bg-paper/95 px-4 backdrop-blur lg:hidden">
        <Wordmark />
        <button className="rounded p-2 text-ink-soft hover:bg-stone" aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>
      {open && (
        <div className="fixed inset-0 top-14 z-20 flex flex-col bg-paper lg:hidden">
          <Nav onNavigate={() => setOpen(false)} />
          <div className="border-t border-stone-line px-5 py-4"><ApiStatus /></div>
        </div>
      )}

      <main id="main" className="min-w-0 px-4 pb-16 pt-6 sm:px-8 lg:px-10 lg:pt-9">
        <div key={location.pathname} className="route-enter mx-auto max-w-[1240px]">
          <DemoNotice />
          <Suspense fallback={<div className="pt-4"><LoadingBlock rows={6} /></div>}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
