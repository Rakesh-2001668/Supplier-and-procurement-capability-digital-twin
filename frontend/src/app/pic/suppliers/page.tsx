'use client';

import { useEffect, useState } from 'react';
import { Card, DataTable, LinkButton, PageHeader, StatusChip } from '@/components/pic/ui';
import { readSessionUser } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useList } from '@/lib/pic/hooks';

type Supplier = { id: string; code: string; legal_name: string; status: string; state_code: string; segment: string | null; risk_tier: string | null;
  payment_terms: string; incoterms: string | null; screening: { outcome?: string } | null; categories: Record<string, string> };

export default function Suppliers() {
  const list = useList<Supplier>('/suppliers');
  const [canRegister, setCanRegister] = useState(false);
  useEffect(() => {
    const roles = readSessionUser()?.roles;
    setCanRegister(!roles || roles.includes('SUPPLIER_MANAGER'));
  }, []);
  return (
    <div>
      <PageHeader eyebrow="SLM-02 · Supplier lifecycle" title="Suppliers"
        subtitle="Status is held per category: a supplier can be Qualified for one category and only Registered for another. Only Qualified or Preferred suppliers can be invited to sourcing."
        actions={<>
          <LinkButton href="/pic/suppliers/risk">Risk monitor (SLM-04)</LinkButton>
          <LinkButton href="/pic/suppliers/performance">Performance (SLM-03)</LinkButton>
          {canRegister && <LinkButton variant="primary" href="/pic/suppliers/new">Register supplier</LinkButton>}
        </>} />
      <Card title="Supplier base">
        <DataTable<Supplier>
          rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} rowHref={(r) => `/pic/suppliers/${encodeURIComponent(r.code)}`} empty="No suppliers"
          columns={[
            { key: 'code', header: 'Code' },
            { key: 'legal_name', header: 'Legal name' },
            { key: 'status', header: 'Supplier status', render: (r) => <StatusChip status={r.status} /> },
            { key: 'categories', header: 'Category status', render: (r) => {
              const entries = Object.entries(r.categories ?? {});
              return entries.length ? (
                <ul className="flex flex-wrap gap-1.5">
                  {entries.map(([cat, st]) => <li key={cat} className="flex items-center gap-1"><span className="font-mono text-[11px] text-slate-600">{cat}</span><StatusChip status={st} /></li>)}
                </ul>
              ) : '–';
            } },
            { key: 'screening', header: 'Screening', render: (r) => (r.screening?.outcome ? <StatusChip status={r.screening.outcome} /> : '–') },
            { key: 'state_code', header: 'State' },
            { key: 'payment_terms', header: 'Terms' },
            { key: 'segment', header: 'Segment', render: (r) => (r.segment ? label(r.segment) : '–') },
          ]}
        />
      </Card>
    </div>
  );
}
