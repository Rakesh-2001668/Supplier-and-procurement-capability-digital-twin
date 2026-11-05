'use client';

import { useState } from 'react';
import { Card, DataTable, LinkButton, PageHeader, Select, StatusChip, Tabs } from '@/components/pic/ui';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useList } from '@/lib/pic/hooks';
import { MANAGE_ROLES, useCan } from './_lib';
import { PipelineView } from './_pipeline';

type SourcingEvent = { id: string; number: string; type: string; title: string; category: string; status: string; round: number;
  close_at: string; published_at: string | null; baseline_price_minor: number | null; created_at: string; open_at?: string | null; competitive?: boolean | null };

const STATUSES = ['', 'DRAFT', 'PUBLISHED', 'OPEN', 'CLOSED', 'UNDER_EVALUATION', 'AWARD_PENDING', 'AWARDED', 'CANCELLED'];

function Worklist() {
  const [status, setStatus] = useState('');
  const list = useList<SourcingEvent>(`/sourcing/events${status ? `?status=${status}` : ''}`);
  return (
    <Card title="Worklist" actions={
      <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
        options={STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
    }>
      <DataTable<SourcingEvent>
        caption="Sourcing events"
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
  );
}

export default function SourcingEvents() {
  const can = useCan();
  const canManage = can(MANAGE_ROLES);
  return (
    <div>
      <PageHeader kpis="M05" eyebrow="SRC-01 · Strategic sourcing" title="Sourcing events"
        subtitle="RFx events start only from approved requirements, invite only suppliers qualified for the category, keep bids sealed until the opening and award on TCO and verified capacity."
        actions={canManage && (
          <>
            <LinkButton href="/pic/sourcing/templates">Templates</LinkButton>
            <LinkButton href="/pic/sourcing/should-cost">Should-cost models</LinkButton>
            <LinkButton href="/pic/sourcing/benchmarks">Benchmarks</LinkButton>
            <LinkButton href="/pic/sourcing/tco">TCO simulator</LinkButton>
            <LinkButton variant="primary" href="/pic/sourcing/new">New sourcing event</LinkButton>
          </>
        )} />
      <Tabs label="Sourcing views" tabs={[
        { id: 'worklist', label: 'Worklist', content: <Worklist /> },
        ...(canManage ? [{ id: 'pipeline', label: 'Pipeline', content: <PipelineView /> }] : []),
      ]} />
    </div>
  );
}
