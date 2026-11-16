import { CheckCircle2, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "./primitives";

/* ---------- Confirm dialog (native <dialog>: focus trap and Esc handling for free) ---------- */

export function ConfirmDialog({ open, title, children, confirmLabel, onConfirm, onCancel, busy, danger }: {
  open: boolean; title: string; children: ReactNode; confirmLabel: string; busy?: boolean; danger?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close?.();
  }, [open]);
  return (
    <dialog ref={ref} onCancel={(e) => { e.preventDefault(); onCancel(); }}
      className="w-[min(92vw,440px)] rounded-md border-0 p-0 shadow-pop backdrop:bg-ink/30">
      {open && (
        <div className="p-6">
          <h2 className="text-md font-semibold text-ink">{title}</h2>
          <div className="mt-2 text-base text-ink-muted">{children}</div>
          <div className="mt-6 flex justify-end gap-2">
            <Button onClick={onCancel} disabled={busy}>Cancel</Button>
            <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={busy}>{confirmLabel}</Button>
          </div>
        </div>
      )}
    </dialog>
  );
}

/* ---------- Toasts ---------- */

interface Toast { id: number; tone: "success" | "error"; text: string }
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(92vw,380px)] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto flex items-start gap-2.5 rounded-md bg-ink px-4 py-3 text-base text-paper shadow-pop">
            {t.tone === "success"
              ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-sage" aria-hidden />
              : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-[#E3A68C]" aria-hidden />}
            <span className="flex-1">{t.text}</span>
            <button aria-label="Dismiss" className="text-paper/60 hover:text-paper"
              onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}>
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
