'use client';

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ApiError } from '@/lib/pic/api';

type Toast = { id: number; kind: 'success' | 'error'; title: string; detail?: string; meta?: string };
type ToastApi = { success: (title: string) => void; problem: (error: ApiError | Error) => void };

const ToastContext = createContext<ToastApi>({ success: () => {}, problem: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all, { ...toast, id }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), toast.kind === 'error' ? 9000 : 4000);
  }, []);
  const value = useMemo<ToastApi>(() => ({
    success: (title) => push({ kind: 'success', title }),
    problem: (error) => {
      const problem = (error as ApiError).problem;
      push({
        kind: 'error',
        title: problem?.title ? String(problem.title).replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : 'Something went wrong',
        detail: problem?.detail ?? error.message,
        meta: [problem?.ruleRef && `Rule ${problem.ruleRef}`, problem?.traceId && `Trace ${problem.traceId}`].filter(Boolean).join(' · '),
      });
    },
  }), [push]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role={t.kind === 'error' ? 'alert' : undefined}
            className="relative flex animate-pop gap-3 overflow-hidden rounded-xl border border-line bg-surface/95 py-3 pl-4 pr-4 text-ink shadow-raised backdrop-blur">
            <span aria-hidden className={`absolute inset-y-0 left-0 w-1 ${t.kind === 'success' ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <span aria-hidden className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white ${t.kind === 'success' ? 'bg-emerald-500' : 'bg-red-500'}`}>
              {t.kind === 'success' ? '✓' : '!'}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold">{t.title}</p>
              {t.detail && <p className="mt-0.5 text-sm text-ink-2">{t.detail}</p>}
              {t.meta && <p className="mt-1 font-mono text-[11px] text-ink-3">{t.meta}</p>}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
