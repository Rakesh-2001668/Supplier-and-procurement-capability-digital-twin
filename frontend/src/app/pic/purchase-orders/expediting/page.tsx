'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Kpi, LinkButton, Loading, PageHeader, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, useSessionUser } from '../../invoices/_components';

type Row = { po: string; line: number; supplier: string; description: string; openQty: string; uom: string; needDate: string | null; daysLate: number;
  status: string; lateProb: string | null; asn: string | null; risk: 'LATE' | 'AT_RISK' | 'ON_TRACK'; valueAtRiskMinor: number };
type Draft = { po: string; line: number; message: string; aiRef: string };

const RISK_STYLE: Record<Row['risk'], string> = {
  LATE: 'bg-red-50 text-red-800 ring-red-200',
  AT_RISK: 'bg-amber-50 text-amber-800 ring-amber-200',
  ON_TRACK: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
};

function RiskChip({ risk }: { risk: Row['risk'] }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${RISK_STYLE[risk]}`}>
      {risk.replace('_', ' ')}
    </span>
  );
}

export default function Expediting() {
  const { data, isLoading, error } = useApi<Row[]>('/expediting');
  const user = useSessionUser();
  const canExpedite = hasRole(user, 'BUYER');
  const [risk, setRisk] = useState('');
  const [target, setTarget] = useState<Row | null>(null);
  const rows = (data ?? []).filter((r) => !risk || r.risk === risk);
  const all = data ?? [];
  const late = all.filter((r) => r.risk === 'LATE');
  const atRisk = all.filter((r) => r.risk === 'AT_RISK');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PO-04 · Expediting" title="Expediting cockpit"
        subtitle="Open schedule lines ranked by delivery risk: days late, the supplier twin's late-delivery probability for the category and whether an ASN has arrived. The Expediting Agent drafts the follow-up; you send it."
        actions={<>
          <LinkButton href="/pic/purchase-orders">Purchase orders</LinkButton>
          <LinkButton href="/pic/purchase-orders/changes">Confirmations & changes</LinkButton>
        </>} />

      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Late lines" value={late.length} hint={late.length ? `worst ${Math.max(...late.map((r) => r.daysLate))} days late` : 'none past need date'}
              tone={late.length ? 'bad' : 'good'} />
            <Kpi label="At risk" value={atRisk.length} hint="twin ≥ 30% late, or due ≤ 7 days with no ASN" tone={atRisk.length ? 'warn' : 'default'} />
            <Kpi label="Value at risk" value={inr(all.reduce((s, r) => s + r.valueAtRiskMinor, 0))} hint="open value on late and at-risk lines" />
            <Kpi label="Open lines" value={all.length} hint={`${all.filter((r) => !r.asn).length} without an ASN`} />
          </div>

          <Card title="Open schedule lines" actions={
            <Select aria-label="Filter by risk" value={risk} onChange={(e) => setRisk(e.target.value)}
              options={[{ value: '', label: 'All risks' }, { value: 'LATE', label: 'Late' }, { value: 'AT_RISK', label: 'At risk' }, { value: 'ON_TRACK', label: 'On track' }]} />
          }>
            {!canExpedite && user && (
              <p className="mb-3 text-xs text-slate-500">Follow-ups are drafted and sent by buyers (scope po:change).</p>
            )}
            <DataTable<Row> rows={rows} empty={risk ? 'No lines with this risk' : 'No open goods lines to expedite'} columns={[
              { key: 'risk', header: 'Risk', render: (r) => <RiskChip risk={r.risk} /> },
              { key: 'po', header: 'PO / line', render: (r) => (
                <span className="whitespace-nowrap"><Link href={`/pic/purchase-orders/${encodeURIComponent(r.po)}`} className="font-medium text-[#1A56DB] hover:underline">{r.po}</Link> / {r.line}</span>
              ) },
              { key: 'supplier', header: 'Supplier' },
              { key: 'description', header: 'Item', className: 'min-w-[200px]' },
              { key: 'openQty', header: 'Open qty', align: 'right', render: (r) => qty(r.openQty, r.uom) },
              { key: 'needDate', header: 'Need date', render: (r) => <span className="whitespace-nowrap">{date(r.needDate)}</span> },
              { key: 'daysLate', header: 'Days late', align: 'right', render: (r) => r.daysLate > 0 ? <span className="font-semibold text-red-700">{r.daysLate}</span> : '0' },
              { key: 'lateProb', header: 'Twin P(late)', align: 'right', render: (r) => r.lateProb === null ? '–' : (
                <span className={Number(r.lateProb) >= 0.3 ? 'font-semibold text-amber-700' : ''}>{Math.round(Number(r.lateProb) * 100)}%</span>
              ) },
              { key: 'asn', header: 'ASN', render: (r) => r.asn ? <span className="font-mono text-xs">{r.asn}</span> : <span className="text-xs text-amber-700">none yet</span> },
              { key: 'valueAtRiskMinor', header: 'Value at risk', align: 'right', render: (r) => r.valueAtRiskMinor ? inr(r.valueAtRiskMinor) : '–' },
              { key: 'action', header: '', render: (r) => canExpedite
                ? <Button variant={r.risk === 'ON_TRACK' ? 'secondary' : 'primary'} onClick={() => setTarget(r)}>Draft follow-up</Button> : null },
            ]} />
          </Card>
        </>
      )}

      {target && <ExpediteDialog row={target} onClose={() => setTarget(null)} />}
    </div>
  );
}

function ExpediteDialog({ row, onClose }: { row: Row; onClose: () => void }) {
  const [message, setMessage] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const cmd = useCommand(() => api.post<Draft>(`/purchase-orders/${encodeURIComponent(row.po)}/expedite`, {
    line: row.line, message: message.trim() || undefined,
  }), { success: `Follow-up for ${row.po}/${row.line} recorded on the PO`, onSuccess: setDraft });

  return (
    <Dialog open title={`Follow up ${row.po} / line ${row.line}`} onClose={onClose}>
      {!draft ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">
            {row.supplier} · {row.description} · {qty(row.openQty, row.uom)} open, needed {date(row.needDate)}
            {row.daysLate > 0 ? <span className="font-semibold text-red-700"> ({row.daysLate} days late)</span> : null}.
          </p>
          <Field label="Message (optional)" hint="Leave empty and the Expediting Agent (L2) drafts it from the open quantity, due date and ASN status.">
            {(id) => <Textarea id={id} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="e.g. Please confirm dispatch date and share the ASN today." />}
          </Field>
          <ProblemBox error={cmd.error} />
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" busy={cmd.isPending} onClick={() => cmd.mutate()}>{message.trim() ? 'Record follow-up' : 'Draft follow-up'}</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Follow-up message</p>
          <blockquote className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900">{draft.message}</blockquote>
          <p className="text-xs text-slate-500">
            Recorded in the audit trail of {draft.po} · AI reference <span className="font-mono">{draft.aiRef}</span>
          </p>
          <div className="flex justify-end gap-2">
            <Button onClick={() => navigator.clipboard?.writeText(draft.message)}>Copy text</Button>
            <Button variant="primary" onClick={onClose}>Done</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
