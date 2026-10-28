'use client';

import { useState } from 'react';
import { Card, DataTable, LinkButton, PageHeader, Select, StatusChip } from '@/components/pic/ui';
import { date, inr, label } from '@/lib/pic/format';
import { useList } from '@/lib/pic/hooks';

type Contract = { id: string; number: string; type: string; title: string; supplier_code: string; status: string; valid_from: string; valid_to: string;
  payment_terms: string; incoterms: string | null; target_value_minor: number; index_ref: { index?: string; band_pct?: string } | null;
  thresholds_hit: number[] | null };

const STATUSES = ['', 'DRAFT', 'IN_NEGOTIATION', 'IN_APPROVAL', 'OUT_FOR_SIGNATURE', 'ACTIVE', 'EXPIRING', 'EXPIRED', 'TERMINATED', 'RENEWED'];

export default function Contracts() {
  const [status, setStatus] = useState('');
  const list = useList<Contract>(`/contracts${status ? `?status=${status}` : ''}`);
  return (
    <div>
      <PageHeader eyebrow="CLM-03 · Contract lifecycle" title="Contracts"
        subtitle="Contracts are drafted from awards with playbook clauses, AI-reviewed, approved, e-signed by both parties and then publish their price validity periods to source determination."
        actions={<>
          <LinkButton href="/pic/contracts/obligations">Obligations & renewals</LinkButton>
          <LinkButton href="/pic/contracts/new" variant="primary">New contract</LinkButton>
        </>} />
      <Card title="Repository" actions={
        <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
          options={STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
      }>
        <DataTable<Contract>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/contracts/${encodeURIComponent(r.number)}`} empty="No contracts"
          columns={[
            { key: 'number', header: 'Contract' },
            { key: 'title', header: 'Title', className: 'max-w-md' },
            { key: 'supplier_code', header: 'Supplier' },
            { key: 'type', header: 'Type', render: (r) => label(r.type) },
            { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'valid_from', header: 'Validity', render: (r) => `${date(r.valid_from)} – ${date(r.valid_to)}` },
            { key: 'target_value_minor', header: 'Target value', align: 'right', render: (r) => inr(r.target_value_minor) },
            { key: 'index_ref', header: 'Index', render: (r) => (r.index_ref?.index ? `${r.index_ref.index} ±${r.index_ref.band_pct ?? '–'}%` : '–') },
            { key: 'thresholds_hit', header: 'Consumption alerts', render: (r) => (r.thresholds_hit?.length ? r.thresholds_hit.map((t) => `${t}%`).join(', ') : '–') },
          ]}
        />
      </Card>
    </div>
  );
}
