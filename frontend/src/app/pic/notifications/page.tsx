'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Empty, Loading, PageHeader, ProblemBox } from '@/components/pic/ui';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useList } from '@/lib/pic/hooks';
import { KindChip, markAllRead, NotificationRow, useOpenNotification } from './_notifications';

const FILTERS = [{ id: 'unread', label: 'Unread', query: '?unread=true' }, { id: 'all', label: 'All', query: '' }];

export default function NotificationsPage() {
  const [filter, setFilter] = useState('unread');
  const client = useQueryClient();
  const open = useOpenNotification();
  const [busy, setBusy] = useState(false);
  const count = useApi<{ unread: number }>('/notifications/unread-count');
  const list = useList<NotificationRow>(`/notifications${FILTERS.find((f) => f.id === filter)!.query}`);
  const unread = count.data?.unread ?? 0;

  async function readAll() {
    setBusy(true);
    try {
      await markAllRead(client);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="M13 · Notifications" title="Notifications"
        subtitle="Tasks waiting for you, escalations, agent recommendations and document events. E-mail copies follow the tenant's notification rule."
        actions={<Button onClick={readAll} busy={busy} disabled={!unread}>Mark all read</Button>} />
      <Card>
        <div role="tablist" className="mb-4 flex gap-1 border-b border-slate-200">
          {FILTERS.map((f) => (
            <button key={f.id} role="tab" aria-selected={filter === f.id} onClick={() => setFilter(f.id)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${filter === f.id ? 'border-[#1A56DB] text-[#1A56DB]' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>
              {f.label}{f.id === 'unread' && unread ? ` (${unread})` : ''}
            </button>
          ))}
        </div>
        {list.error ? <ProblemBox error={list.error} /> : list.isLoading ? <Loading /> : !list.items.length ? (
          <Empty title={filter === 'unread' ? 'No unread notifications' : 'No notifications yet'}
            hint="You are notified when a task is assigned to you, when it becomes overdue, and when documents you own change." />
        ) : (
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {list.items.map((n) => (
              <li key={n.id} className={`flex flex-wrap items-start justify-between gap-3 px-4 py-3 ${n.read_at ? '' : 'bg-blue-50/40'}`}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <KindChip kind={n.kind} />
                    {n.object_ref && <span className="font-mono text-xs text-slate-500">{label(n.object_type)} · {n.object_ref}</span>}
                  </div>
                  <p className={`mt-1 text-sm ${n.read_at ? 'text-slate-800' : 'font-semibold text-slate-900'}`}>{n.title}</p>
                  <p className="whitespace-pre-line text-sm text-slate-600">{n.body}</p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {dateTime(n.created_at)}{n.read_at ? ` · read ${dateTime(n.read_at)}` : ''} · e-mail {label(n.email_status).toLowerCase()}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  {n.link && <Button onClick={() => open(n)}>Open</Button>}
                  {!n.read_at && !n.link && <Button variant="ghost" onClick={() => open(n)}>Mark read</Button>}
                </div>
              </li>
            ))}
          </ul>
        )}
        {list.hasNextPage && (
          <div className="mt-3 text-center"><Button onClick={() => list.fetchNextPage()} busy={list.isFetchingNextPage}>Load more</Button></div>
        )}
      </Card>
    </div>
  );
}
