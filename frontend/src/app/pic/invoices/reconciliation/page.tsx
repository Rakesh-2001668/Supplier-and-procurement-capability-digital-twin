'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Kpi, LinkButton, Loading, PageHeader, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api, Paged } from '@/lib/pic/api';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, useSessionUser } from '../_components';

type Item = { id: string; kind: string; ref: string; erpDocNo: string | null; platformMinor: number | null; erpMinor: number | null; status: string;
  resolution: string | null };
type Run = { number: string; system: string; companyCode: string; asOf: string; platformCount: number; erpCount: number; platformMinor: number;
  erpMinor: number; differences: number; items: Item[] };
type Message = { id: string; status: string };

const KIND_TEXT: Record<string, string> = {
  MISSING_IN_ERP: 'Posted in the platform, no ERP document found',
  MISSING_IN_PLATFORM: 'ERP document with no matching platform posting',
  AMOUNT_MISMATCH: 'Amounts differ (platform gross net of credit notes vs ERP)',
  DOCUMENT_MISMATCH: 'ERP document number differs from the one recorded',
  PAYMENT_MISSING_IN_ERP: 'Payment made in a run, no ERP clearing document yet',
  PAYMENT_AMOUNT_MISMATCH: 'Payment amount differs from the ERP clearing document',
  PAYMENT_NOT_IN_PLATFORM: 'ERP payment with no matching platform payment',
  MEMO_MISSING_IN_ERP: 'Credit note received after posting, no ERP credit memo yet',
  MEMO_AMOUNT_MISMATCH: 'Credit memo amount differs from the credit note',
};

export default function Reconciliation() {
  const user = useSessionUser();
  const canRun = hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER');
  const { data, isLoading, error } = useApi<Run[]>('/reconciliation/runs');
  const [selected, setSelected] = useState<string | null>(null);
  const [resolving, setResolving] = useState<Item | null>(null);
  const run = useCommand(() => api.post<Run>('/reconciliation/runs', { company_code: '1000' }), {
    success: (r) => `${r.number}: ${r.differences} difference${r.differences === 1 ? '' : 's'}`, onSuccess: (r) => setSelected(r.number),
  });
  const current = data?.find((r) => r.number === selected) ?? data?.[0] ?? null;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="INV-03 · Posting & reconciliation" title="ERP posting reconciliation"
        subtitle="Platform invoice postings are compared with the ERP's supplier-invoice documents by count, amount and document number. Every difference is listed and resolved with a reason."
        actions={<>
          <LinkButton href="/pic/invoices">Invoices</LinkButton>
          <LinkButton href="/pic/invoices/insights">Payables insights</LinkButton>
          {canRun && <Button variant="primary" busy={run.isPending} onClick={() => run.mutate()}>Run reconciliation</Button>}
        </>} />

      <ProblemBox error={run.error} />

      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !current ? (
        <Card><Empty title="No reconciliation has run yet" hint={canRun ? 'Run one now for company code 1000.' : 'Accounts payable or finance runs it.'} /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Platform postings" value={current.platformCount} hint={inr(current.platformMinor)} />
            <Kpi label={`${current.system} documents`} value={current.erpCount} hint={inr(current.erpMinor)} />
            <Kpi label="Amount difference" value={inr(current.platformMinor - current.erpMinor)}
              tone={current.platformMinor === current.erpMinor ? 'good' : 'bad'} />
            <Kpi label="Open differences" value={current.items.filter((i) => i.status === 'OPEN').length}
              hint={`${current.differences} found in ${current.number}`} tone={current.items.some((i) => i.status === 'OPEN') ? 'warn' : 'good'} />
          </div>

          <Card title={<span>Run <span className="font-mono">{current.number}</span></span>}>
            <Facts items={[
              ['Target system', current.system], ['Company code', current.companyCode], ['As of', dateTime(current.asOf)],
              ['Result', current.differences ? `${current.differences} difference(s)` : 'In balance'],
            ]} />
            <div className="mt-4">
              <DataTable<Item> rows={current.items} empty="Platform and ERP agree: no differences in this run" columns={[
                { key: 'kind', header: 'Difference', className: 'min-w-[220px]', render: (i) => (
                  <span><span className="font-medium">{label(i.kind)}</span><span className="block text-xs text-slate-500">{KIND_TEXT[i.kind] ?? ''}</span></span>
                ) },
                { key: 'ref', header: 'Invoice / key', render: (i) => <span className="font-mono text-xs">{i.ref}</span> },
                { key: 'erpDocNo', header: 'ERP doc', render: (i) => i.erpDocNo ?? '–' },
                { key: 'platformMinor', header: 'Platform', align: 'right', render: (i) => inr(i.platformMinor) },
                { key: 'erpMinor', header: 'ERP', align: 'right', render: (i) => inr(i.erpMinor) },
                { key: 'status', header: 'Status', render: (i) => <StatusChip status={i.status} /> },
                { key: 'resolution', header: 'Resolution', className: 'max-w-xs', render: (i) => i.resolution ?? '–' },
                { key: 'action', header: '', render: (i) => i.status === 'OPEN' && canRun ? <Button onClick={() => setResolving(i)}>Resolve</Button> : null },
              ]} />
            </div>
          </Card>

          <Card title="Run history">
            <DataTable<Run> rows={data ?? []} columns={[
              { key: 'number', header: 'Run', render: (r) => (
                <button type="button" onClick={() => setSelected(r.number)} aria-pressed={r.number === current.number}
                  className={`font-mono text-xs font-semibold hover:underline ${r.number === current.number ? 'text-[#0B1020] underline' : 'text-[#1A56DB]'}`}>{r.number}</button>
              ) },
              { key: 'asOf', header: 'As of', render: (r) => dateTime(r.asOf) },
              { key: 'companyCode', header: 'Company' },
              { key: 'platformCount', header: 'Platform', align: 'right', render: (r) => `${r.platformCount} · ${inr(r.platformMinor)}` },
              { key: 'erpCount', header: 'ERP', align: 'right', render: (r) => `${r.erpCount} · ${inr(r.erpMinor)}` },
              { key: 'differences', header: 'Differences', align: 'right', render: (r) => r.differences ? <span className="font-semibold text-amber-700">{r.differences}</span> : '0' },
            ]} />
          </Card>
        </>
      )}

      <IntegrationStatus admin={hasRole(user, 'TENANT_ADMIN')} />

      {resolving && <ResolveDialog item={resolving} onClose={() => setResolving(null)} />}
    </div>
  );
}

function IntegrationStatus({ admin }: { admin: boolean }) {
  const pending = useApi<Paged<Message>>(admin ? '/integration/messages?status=PENDING&limit=100' : null);
  const retry = useApi<Paged<Message>>(admin ? '/integration/messages?status=RETRY&limit=100' : null);
  const dead = useApi<Paged<Message>>(admin ? '/integration/messages?status=DEAD_LETTER&limit=100' : null);
  const count = (q: typeof pending) => (q.data ? `${q.data.items.length}${q.data.nextCursor ? '+' : ''}` : '–');
  return (
    <Card title="ERP integration messages" actions={<LinkButton href="/pic/admin">Open integration monitor</LinkButton>}>
      <p className="text-sm text-slate-600">
        A posting missing in the ERP is often still queued or dead-lettered. The integration monitor (ADM-05, Administration → Integration monitor) shows each
        outbound message with its idempotency key and lets the administrator replay it without double-posting.
      </p>
      {admin ? (
        pending.error ? <div className="mt-3"><ProblemBox error={pending.error} /></div> : (
          <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-lg border border-slate-200 px-3 py-2"><dt className="text-xs text-slate-500">Pending</dt><dd className="text-lg font-semibold tabular-nums">{count(pending)}</dd></div>
            <div className="rounded-lg border border-amber-200 px-3 py-2"><dt className="text-xs text-slate-500">Retrying</dt><dd className="text-lg font-semibold tabular-nums text-amber-700">{count(retry)}</dd></div>
            <div className="rounded-lg border border-red-200 px-3 py-2"><dt className="text-xs text-slate-500">Dead letter</dt><dd className="text-lg font-semibold tabular-nums text-red-700">{count(dead)}</dd></div>
          </dl>
        )
      ) : (
        <p className="mt-2 text-xs text-slate-500">Message status is visible to the tenant administrator (<Link href="/pic/admin" className="text-[#1A56DB] hover:underline">Administration</Link>).</p>
      )}
    </Card>
  );
}

function ResolveDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  const [resolution, setResolution] = useState('');
  const cmd = useCommand(() => api.post(`/reconciliation/items/${item.id}/resolve`, { resolution: resolution.trim() }), {
    success: `${item.ref} resolved`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Resolve ${label(item.kind).toLowerCase()} · ${item.ref}`} onClose={onClose}>
      <div className="space-y-3">
        <Facts items={[['Platform', inr(item.platformMinor)], ['ERP', inr(item.erpMinor)], ['ERP doc', item.erpDocNo ?? '–'], ['Kind', label(item.kind)]]} />
        <Field label="Resolution (required)" hint="Written to the audit trail, e.g. the corrected ERP document or why the difference is expected.">
          {(id) => <Textarea id={id} value={resolution} onChange={(e) => setResolution(e.target.value)} placeholder="e.g. Message replayed from the integration monitor; ERP doc 5105600123 now posted" />}
        </Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={resolution.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>Resolve</Button>
        </div>
      </div>
    </Dialog>
  );
}
