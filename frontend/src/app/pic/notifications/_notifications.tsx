'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

export type NotificationRow = {
  id: string; kind: string; title: string; body: string; link: string | null; object_type: string | null; object_ref: string | null;
  read_at: string | null; email_status: string; emailed_at: string | null; created_at: string;
};
export type NotificationPage = { items: NotificationRow[]; nextCursor: string | null; unread: number };

export const KIND_TONE: Record<string, string> = {
  TASK_ASSIGNED: 'bg-blue-50 text-blue-800 ring-blue-200', TASK_ESCALATED: 'bg-red-50 text-red-800 ring-red-200',
  RECOMMENDATION: 'bg-violet-50 text-violet-800 ring-violet-200', INVOICE_EXCEPTION: 'bg-amber-50 text-amber-800 ring-amber-200',
  CHANGE_REQUEST: 'bg-amber-50 text-amber-800 ring-amber-200', CONTRACT_TERMINATED: 'bg-red-50 text-red-800 ring-red-200',
};

export function KindChip({ kind }: { kind: string }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${KIND_TONE[kind] ?? 'bg-slate-50 text-slate-700 ring-slate-200'}`}>
      {label(kind)}
    </span>
  );
}

/** Mark as read, then follow the deep link. */
export function useOpenNotification() {
  const client = useQueryClient();
  const router = useRouter();
  return async (n: NotificationRow) => {
    if (!n.read_at) {
      try {
        await api.post(`/notifications/${n.id}/read`, {}, { idempotencyKey: false });
      } finally {
        client.invalidateQueries({ predicate: (q) => String(q.queryKey[0] ?? '').startsWith('/notifications') });
      }
    }
    if (n.link) router.push(n.link);
  };
}

export async function markAllRead(client: ReturnType<typeof useQueryClient>) {
  await api.post('/notifications/read-all', {}, { idempotencyKey: false });
  await client.invalidateQueries({ predicate: (q) => String(q.queryKey[0] ?? '').startsWith('/notifications') });
}

/** Header bell: unread badge and the latest notifications. */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const client = useQueryClient();
  const openNotification = useOpenNotification();
  const count = useApi<{ unread: number }>('/notifications/unread-count', { refetchInterval: 30000 });
  const latest = useApi<NotificationPage>(open ? '/notifications?limit=8' : null);
  const unread = count.data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="true" aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        className="relative rounded-md p-1.5 text-slate-600 hover:bg-slate-100">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-red-600 px-1 text-center text-[10px] font-bold leading-[18px] text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <p className="text-sm font-semibold">Notifications</p>
            {unread > 0 && (
              <button className="text-xs font-medium text-[#1A56DB] hover:underline" onClick={() => markAllRead(client)}>Mark all read</button>
            )}
          </div>
          <ul className="max-h-[26rem] divide-y divide-slate-100 overflow-y-auto">
            {latest.isLoading && <li className="px-4 py-6 text-center text-sm text-slate-500">Loading…</li>}
            {latest.error && <li className="px-4 py-6 text-center text-sm text-red-700">{latest.error.message}</li>}
            {latest.data && !latest.data.items.length && <li className="px-4 py-6 text-center text-sm text-slate-500">You are all caught up.</li>}
            {latest.data?.items.map((n) => (
              <li key={n.id}>
                <button onClick={() => { setOpen(false); openNotification(n); }}
                  className={`block w-full px-4 py-2.5 text-left hover:bg-slate-50 ${n.read_at ? '' : 'bg-blue-50/40'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <KindChip kind={n.kind} />
                    <span className="text-[11px] text-slate-500">{dateTime(n.created_at)}</span>
                  </div>
                  <p className={`mt-1 text-sm ${n.read_at ? 'text-slate-700' : 'font-semibold text-slate-900'}`}>{n.title}</p>
                  <p className="line-clamp-2 text-xs text-slate-600">{n.body}</p>
                </button>
              </li>
            ))}
          </ul>
          <Link href="/pic/notifications" prefetch={false} onClick={() => setOpen(false)}
            className="block border-t border-slate-100 px-4 py-2 text-center text-xs font-medium text-[#1A56DB] hover:bg-slate-50">
            See all notifications
          </Link>
        </div>
      )}
    </div>
  );
}
