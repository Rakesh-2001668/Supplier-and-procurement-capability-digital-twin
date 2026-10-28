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
          <div key={t.id} className={`rounded-lg border px-4 py-3 shadow-lg ${t.kind === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-red-200 bg-red-50 text-red-900'}`}>
            <p className="text-sm font-semibold">{t.title}</p>
            {t.detail && <p className="mt-0.5 text-sm">{t.detail}</p>}
            {t.meta && <p className="mt-1 font-mono text-[11px] opacity-70">{t.meta}</p>}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
