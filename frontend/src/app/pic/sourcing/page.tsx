'use client';

import { useMemo, useState, useSyncExternalStore } from 'react';
import { Card, DataTable, LinkButton, PageHeader, Select, StatusChip } from '@/components/pic/ui';
import { readSessionUser } from '@/lib/pic/api';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useList } from '@/lib/pic/hooks';

type SourcingEvent = { id: string; number: string; type: string; title: string; category: string; status: string; round: number;
  close_at: string; published_at: string | null; baseline_price_minor: number | null; created_at: string };

const STATUSES = ['', 'DRAFT', 'OPEN', 'UNDER_EVALUATION', 'AWARD_PENDING', 'AWARDED', 'CANCELLED'];
const MANAGERS = ['BUYER', 'CATEGORY_MANAGER'];
const noSubscribe = () => () => {};

export default function SourcingEvents() {
  const [status, setStatus] = useState('');
  const list = useList<SourcingEvent>(`/sourcing/events${status ? `?status=${status}` : ''}`);
  // Read the session cookie on the client only (server snapshot null), so server and client render the same markup.
  const cookie = useSyncExternalStore(noSubscribe, () => document.cookie, () => null);
  const canCreate = useMemo(() => {
    if (cookie === null) return false;
    const roles = readSessionUser()?.roles;
    return !roles || roles.some((r) => MANAGERS.includes(r));
  }, [cookie]);
  return (
    <div>
      <PageHeader eyebrow="SRC-01 · Strategic sourcing" title="Sourcing events"
        subtitle="RFx events start only from approved requirements, invite only suppliers qualified for the category, keep bids sealed until close and award on TCO and verified capacity."
        actions={canCreate && <LinkButton variant="primary" href="/pic/sourcing/new">New sourcing event</LinkButton>} />
      <Card title="Worklist" actions={
        <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
          options={STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
      }>
        <DataTable<SourcingEvent>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/sourcing/${encodeURIComponent(r.number)}`} empty="No sourcing events"
          columns={[
            { key: 'number', header: 'Event' },
            { key: 'type', header: 'Type', render: (r) => r.type.replace(/_/g, ' ') },
            { key: 'title', header: 'Title', className: 'max-w-md' },
            { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs">{r.category}</span> },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'round', header: 'Round', align: 'right' },
            { key: 'close_at', header: 'Closes', render: (r) => dateTime(r.close_at) },
            { key: 'baseline_price_minor', header: 'Baseline / unit', align: 'right', render: (r) => inr(r.baseline_price_minor) },
          ]}
        />
      </Card>
    </div>
  );
}
