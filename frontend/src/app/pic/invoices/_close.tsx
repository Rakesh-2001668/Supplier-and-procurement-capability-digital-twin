'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { downloadFile } from '../purchase-orders/[ref]/_ops';
import { hasRole, useSessionUser } from './_components';

type Cutoff = { periodEnd: string; unpostedInvoices: number; unpostedGrossMinor: number; unpostedByStatus: Record<string, number>; grirAccrualMinor: number };
type Period = { id: string; companyCode: string; period: string; status: 'OPEN' | 'CLOSED'; closedAt: string | null; reopenedAt: string | null; reason: string | null;
  cutoff: Cutoff | Record<string, never> };

/** The last twelve completed calendar months, most recent first, as YYYY-MM (the current month cannot be closed before it ends). */
function recentPeriods(): string[] {
  const now = new Date();
  return Array.from({ length: 12 }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() - i - 1, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  });
}

/** Period close and cut-off (INV-03): no invoice is posted, and no payment dated, into a closed period; closing records what is still in flight. */
export function PostingPeriodsCard() {
  const user = useSessionUser();
  const canClose = hasRole(user, 'FINANCE_CONTROLLER');
  const periods = useApi<{ items: Period[] }>('/finance/periods');
  // Refused attempts to post into a closed period are audited (POSTING_REFUSED); the audit explorer needs the audit scope, so only those users see the evidence.
  const me = useApi<{ scopes: string[] }>('/me');
  const canAudit = !!me.data?.scopes.includes('admin:audit');
  const refusals = useApi<{ items: { objectRef: string; actor: string; ts: string; reason: string | null }[] }>(
    canAudit ? '/audit?object_type=POSTING_PERIOD&action=POSTING_REFUSED&limit=500' : null);
  const refused = (p: Period) => (refusals.data?.items ?? []).filter((e) => e.objectRef === `${p.companyCode}/${p.period}`);
  const [companyCode, setCompanyCode] = useState('1000');
  const [period, setPeriod] = useState(recentPeriods()[0]);
  const [reason, setReason] = useState('');
  const [reopen, setReopen] = useState<Period | null>(null);
  const [cutoff, setCutoff] = useState<Cutoff | null>(null);
  const preview = useCommand(() => api.get<Cutoff>(`/finance/periods/${period}/cutoff?company_code=${encodeURIComponent(companyCode.trim())}`), { onSuccess: setCutoff });
  const close = useCommand(() => api.post<Period>(`/finance/periods/${period}/close`, { companyCode: companyCode.trim(), reason: reason.trim() || undefined }), {
    success: (p) => `${p.companyCode} ${p.period} closed`, onSuccess: () => { setCutoff(null); setReason(''); },
  });
  return (
    <Card title="Posting periods · cut-off">
      {periods.isLoading ? <Loading /> : periods.error ? <ProblemBox error={periods.error} /> : (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            A closed period takes no invoice, credit note, debit note or goods receipt posted or dated into it, and no payment dated into it. Closing records the cut-off (invoices still in flight) and stores the received-not-invoiced (GR/IR) accrual line by line. Reopening needs finance and an audited reason; close the period again afterwards.
          </p>
          {canClose && (
            <div className="grid gap-3 md:grid-cols-4">
              <Field label="Company code">{(id) => <Input id={id} maxLength={10} value={companyCode} onChange={(e) => { setCompanyCode(e.target.value); setCutoff(null); }} />}</Field>
              <Field label="Period">{(id) => <Select id={id} value={period} onChange={(e) => { setPeriod(e.target.value); setCutoff(null); }}
                options={recentPeriods().map((p) => ({ value: p, label: p }))} />}</Field>
              <div className="md:col-span-2">
                <Field label="Reason (optional)">{(id) => <Input id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
              </div>
              <div className="flex gap-2 md:col-span-4">
                <Button busy={preview.isPending} disabled={!companyCode.trim()} onClick={() => preview.mutate()}>Preview cut-off</Button>
                <Button variant="primary" busy={close.isPending} disabled={!companyCode.trim()} onClick={() => close.mutate()}>Close period</Button>
              </div>
            </div>
          )}
          {cutoff && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm" aria-label="Cut-off preview">
              <p className="font-medium">Cut-off at {cutoff.periodEnd}</p>
              <p>{cutoff.unpostedInvoices} invoice(s) not yet posted · {inr(cutoff.unpostedGrossMinor)}
                {Object.entries(cutoff.unpostedByStatus).length ? ` (${Object.entries(cutoff.unpostedByStatus).map(([s, n]) => `${n} ${s.toLowerCase()}`).join(', ')})` : ''}</p>
              <p>GR/IR accrual {inr(cutoff.grirAccrualMinor)}</p>
            </div>
          )}
          {!canAudit && <p className="text-xs text-slate-500">An attempt to post or date a document into a closed period is refused and audited with who tried what; the tenant administrator sees these in the audit explorer (action POSTING_REFUSED).</p>}
          {!periods.data?.items.length ? <Empty title="No period has been closed" hint="Every period is open." /> : (
            <DataTable<Period> rows={periods.data.items} columns={[
              { key: 'companyCode', header: 'Company' },
              { key: 'period', header: 'Period', render: (p) => <span className="font-mono">{p.period}</span> },
              { key: 'status', header: 'Status', render: (p) => <StatusChip status={p.status} /> },
              { key: 'closedAt', header: 'Closed', render: (p) => (p.closedAt ? dateTime(p.closedAt) : '–') },
              { key: 'reopenedAt', header: 'Reopened', render: (p) => (p.reopenedAt ? dateTime(p.reopenedAt) : '–') },
              { key: 'cutoff', header: 'In flight at close', render: (p) => ('unpostedInvoices' in p.cutoff
                ? `${p.cutoff.unpostedInvoices} invoice(s) · GR/IR ${inr(p.cutoff.grirAccrualMinor)}` : '–') },
              { key: 'reason', header: 'Reason', className: 'min-w-[200px]', render: (p) => p.reason ?? '–' },
              ...(canAudit ? [{ key: 'refused', header: 'Refused postings', render: (p: Period) => {
                const hits = refused(p);
                return hits.length ? <span className="text-amber-800" title={hits.map((h) => `${h.actor} ${dateTime(h.ts)}`).join('; ')}>{hits.length} · last {dateTime(hits[0].ts)} by {hits[0].actor}</span> : '0';
              } }] : []),
              { key: 'action', header: '', render: (p) => canClose && p.status === 'CLOSED' ? <Button onClick={() => setReopen(p)}>Reopen</Button> : null },
            ]} />
          )}
        </div>
      )}
      {reopen && <ReopenDialog period={reopen} onClose={() => setReopen(null)} />}
    </Card>
  );
}

function ReopenDialog({ period, onClose }: { period: Period; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.post<Period>(`/finance/periods/${period.period}/reopen`, { companyCode: period.companyCode, reason: reason.trim() }), {
    success: (p) => `${p.companyCode} ${p.period} reopened`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Reopen ${period.companyCode} ${period.period}`} onClose={onClose}>
      <Field label="Reason (at least 10 characters)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <p className="mt-2 text-xs text-slate-500">Reopening is audited with who and why; close the period again when the late entries are booked.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={reason.trim().length < 10} busy={save.isPending} onClick={() => save.mutate()}>Reopen period</Button>
      </div>
    </Dialog>
  );
}

const QUARTERS = [{ value: 'Q1', label: 'Q1 April–June' }, { value: 'Q2', label: 'Q2 July–September' }, { value: 'Q3', label: 'Q3 October–December' }, { value: 'Q4', label: 'Q4 January–March' }];
const FORMS = [{ value: '26Q', label: '26Q · residents, one line per payment' }, { value: '27Q', label: '27Q · non-residents (s.195), one line per payment' },
  { value: '16A', label: '16A · totals per deductee and section' }];

/** The fiscal year (April to March) of today as YYYY-YY. */
function currentFiscalYear(): string {
  const now = new Date();
  const start = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}-${String(start + 1).slice(-2)}`;
}

/** Form 26Q / 16A style CSV of the TDS deducted in a quarter (finance only; every export is audited with its hash). */
export function TdsExportCard() {
  const user = useSessionUser();
  const [fiscalYear, setFiscalYear] = useState(currentFiscalYear());
  const [quarter, setQuarter] = useState('Q1');
  const [form, setForm] = useState('26Q');
  const [error, setError] = useState<Error | null>(null);
  if (!hasRole(user, 'FINANCE_CONTROLLER')) return null;
  const valid = /^\d{4}-\d{2}$/.test(fiscalYear);
  return (
    <Card title="TDS return export">
      <div className="grid gap-3 md:grid-cols-4">
        <Field label="Fiscal year" hint="e.g. 2026-27">{(id) => <Input id={id} maxLength={7} value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} />}</Field>
        <Field label="Quarter">{(id) => <Select id={id} value={quarter} onChange={(e) => setQuarter(e.target.value)} options={QUARTERS} />}</Field>
        <Field label="Layout">{(id) => <Select id={id} value={form} onChange={(e) => setForm(e.target.value)} options={FORMS} />}</Field>
        <div className="flex items-end">
          <Button variant="primary" disabled={!valid} onClick={() => {
            setError(null);
            downloadFile(`/finance/tds-export?fiscal_year=${fiscalYear}&quarter=${quarter}&format=${form}`, `TDS_${form}_${fiscalYear}_${quarter}.csv`).catch(setError);
          }}>Download CSV</Button>
        </div>
      </div>
      <ProblemBox error={error} />
      <p className="mt-2 text-xs text-slate-500">Payments completed in the quarter with TDS deducted or a lower-deduction certificate applied. The PAN is the one inside the supplier&apos;s GSTIN.</p>
    </Card>
  );
}
