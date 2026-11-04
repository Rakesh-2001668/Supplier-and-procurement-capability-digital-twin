'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { downloadFile } from '../purchase-orders/[ref]/_ops';
import { hasRole, isPositive, today, useSessionUser } from './_components';
import { TdsExportCard } from './_close';

// ---------------------------------------------------------------- fiscal period helpers (Indian fiscal year April to March)
const QUARTERS = [{ value: 'Q1', label: 'Q1 April–June' }, { value: 'Q2', label: 'Q2 July–September' }, { value: 'Q3', label: 'Q3 October–December' }, { value: 'Q4', label: 'Q4 January–March' }];

function currentPeriod(): { fiscalYear: string; quarter: string } {
  const [y, m] = today().split('-').map(Number);
  const start = m >= 4 ? y : y - 1;
  return { fiscalYear: `${start}-${String(start + 1).slice(-2)}`, quarter: m >= 4 && m <= 6 ? 'Q1' : m >= 7 && m <= 9 ? 'Q2' : m >= 10 ? 'Q3' : 'Q4' };
}

/** First day of a quarter, YYYY-MM-DD. */
function quarterStart(fiscalYear: string, quarter: string): string {
  const start = Number(fiscalYear.slice(0, 4));
  return { Q1: `${start}-04-01`, Q2: `${start}-07-01`, Q3: `${start}-10-01`, Q4: `${start + 1}-01-01` }[quarter] ?? `${start}-04-01`;
}

const FY_RE = /^\d{4}-\d{2}$/;
const fyValid = (fy: string) => FY_RE.test(fy) && Number(fy.slice(5)) === (Number(fy.slice(0, 4)) + 1) % 100;

function PeriodFields({ value, onChange }: { value: { fiscalYear: string; quarter: string }; onChange: (v: { fiscalYear: string; quarter: string }) => void }) {
  return (
    <>
      <Field label="Fiscal year" hint="e.g. 2026-27" error={value.fiscalYear && !fyValid(value.fiscalYear) ? 'Write it as 2026-27' : undefined}>
        {(id, d) => <Input id={id} aria-describedby={d} maxLength={7} value={value.fiscalYear} onChange={(e) => onChange({ ...value, fiscalYear: e.target.value.trim() })} />}
      </Field>
      <Field label="Quarter">{(id) => <Select id={id} value={value.quarter} onChange={(e) => onChange({ ...value, quarter: e.target.value })} options={QUARTERS} />}</Field>
    </>
  );
}

type Sections = Record<string, { label: string | null; ratePct: number }>;

// ---------------------------------------------------------------- TDS challans and the deducted-against-deposited reconciliation
type Challan = { id: string; companyCode: string; fiscalYear: string; quarter: string; section: string; challanNo: string; bsrCode: string; depositDate: string;
  amountMinor: number; status: 'RECORDED' | 'VOID'; note: string | null };
type ReconRow = { companyCode: string; section: string; deductedMinor: number; depositedMinor: number; challans: number; differenceMinor: number; status: string };
type Recon = { fiscalYear: string; quarter: string; from: string; to: string; rows: ReconRow[]; deductedMinor: number; depositedMinor: number; differenceMinor: number; reconciled: boolean };

const DIFFERENCE_TEXT: Record<string, string> = { RECONCILED: 'deducted and deposited agree', SHORT_DEPOSITED: 'still to be deposited', EXCESS_DEPOSITED: 'deposited in excess' };

export function ChallansTab() {
  const user = useSessionUser();
  const canWrite = hasRole(user, 'FINANCE_CONTROLLER');
  const [period, setPeriod] = useState(currentPeriod());
  const ok = fyValid(period.fiscalYear);
  const query = `fiscal_year=${period.fiscalYear}&quarter=${period.quarter}`;
  const recon = useApi<Recon>(ok ? `/finance/tds-challans/reconciliation?${query}` : null);
  const challans = useApi<{ items: Challan[] }>(ok ? `/finance/tds-challans?${query}` : null);
  const [recording, setRecording] = useState<Partial<ReconRow> | null>(null);
  const [voiding, setVoiding] = useState<Challan | null>(null);
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <PeriodFields value={period} onChange={setPeriod} />
        {canWrite && <div className="flex items-end"><Button variant="primary" onClick={() => setRecording({})}>Record challan</Button></div>}
      </div>

      <Card title={`Deducted against deposited · ${period.fiscalYear} ${period.quarter}`}>
        {!ok ? <Empty title="Enter the fiscal year as 2026-27" /> : recon.isLoading ? <Loading /> : recon.error ? <ProblemBox error={recon.error} /> : recon.data && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi label="TDS deducted" value={inr(recon.data.deductedMinor)} hint={`payments dated ${date(recon.data.from)} to ${date(recon.data.to)}`} />
              <Kpi label="Deposited by challans" value={inr(recon.data.depositedMinor)} hint="voided challans do not count" />
              <Kpi label="Difference" value={inr(recon.data.differenceMinor)} tone={recon.data.differenceMinor === 0 ? 'good' : recon.data.differenceMinor > 0 ? 'warn' : 'bad'}
                hint={recon.data.differenceMinor > 0 ? 'still to be deposited' : recon.data.differenceMinor < 0 ? 'deposited in excess' : 'nothing open'} />
              <Kpi label="Status" value={recon.data.reconciled ? 'Reconciled' : 'Open'} tone={recon.data.reconciled ? 'good' : 'warn'}
                hint={recon.data.rows.length ? `${recon.data.rows.length} company code and section line(s)` : 'no TDS deducted in the quarter'} />
            </div>
            <DataTable<ReconRow & { id: string }> rows={recon.data.rows.map((r) => ({ ...r, id: `${r.companyCode}-${r.section}` }))} empty="No TDS was deducted and no challan was deposited in this quarter"
              caption="TDS deducted against deposited by company code and section" columns={[
                { key: 'companyCode', header: 'Company code' },
                { key: 'section', header: 'Section', render: (r) => <span className="font-mono text-xs">{r.section}</span> },
                { key: 'deductedMinor', header: 'Deducted', align: 'right', render: (r) => inr(r.deductedMinor) },
                { key: 'depositedMinor', header: 'Deposited', align: 'right', render: (r) => inr(r.depositedMinor) },
                { key: 'challans', header: 'Challans', align: 'right' },
                { key: 'differenceMinor', header: 'Difference', align: 'right', render: (r) => (
                  <span className={r.differenceMinor > 0 ? 'font-semibold text-amber-700' : r.differenceMinor < 0 ? 'font-semibold text-red-700' : ''}>{inr(r.differenceMinor)}</span>) },
                { key: 'status', header: 'Status', render: (r) => <span><StatusChip status={r.status} /><span className="ml-1 text-xs text-slate-500">{DIFFERENCE_TEXT[r.status]}</span></span> },
                { key: 'action', header: '', render: (r) => canWrite && r.differenceMinor > 0
                  ? <Button aria-label={`Record a challan for ${r.companyCode} ${r.section}`} onClick={() => setRecording(r)}>Record challan</Button> : null },
              ]} />
          </div>
        )}
      </Card>

      <Card title="Challans">
        <DataTable<Challan> rows={challans.data?.items ?? []} loading={challans.isLoading} error={challans.error} empty="No challan recorded for this quarter"
          caption="TDS deposit challans" columns={[
            { key: 'depositDate', header: 'Deposit date', render: (c) => date(c.depositDate) },
            { key: 'companyCode', header: 'Company code' },
            { key: 'section', header: 'Section', render: (c) => <span className="font-mono text-xs">{c.section}</span> },
            { key: 'challanNo', header: 'Challan serial', render: (c) => <span className="font-mono text-xs">{c.challanNo}</span> },
            { key: 'bsrCode', header: 'BSR code', render: (c) => <span className="font-mono text-xs">{c.bsrCode}</span> },
            { key: 'amountMinor', header: 'Amount', align: 'right', render: (c) => (c.status === 'VOID' ? <s className="text-slate-400">{inr(c.amountMinor)}</s> : inr(c.amountMinor)) },
            { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
            { key: 'note', header: 'Note', className: 'min-w-[160px]', render: (c) => c.note ?? '–' },
            { key: 'action', header: '', render: (c) => canWrite && c.status === 'RECORDED' ? <Button variant="danger" aria-label={`Void challan ${c.challanNo}`} onClick={() => setVoiding(c)}>Void</Button> : null },
          ]} />
        <p className="mt-2 text-xs text-slate-500">A voided challan stays on record and no longer counts as deposited. Challan serial and BSR code come from the bank&apos;s challan receipt (OLTAS).</p>
      </Card>
      {recording && <ChallanDialog period={period} preset={recording} onClose={() => setRecording(null)} />}
      {voiding && <VoidChallanDialog challan={voiding} onClose={() => setVoiding(null)} />}
    </div>
  );
}

function ChallanDialog({ period, preset, onClose }: { period: { fiscalYear: string; quarter: string }; preset: Partial<ReconRow>; onClose: () => void }) {
  const controls = useApi<{ tds: { sections: Sections } }>('/finance/controls');
  const me = useApi<{ attributes: { company_codes?: string[] } }>('/me');
  const [companyCode, setCompanyCode] = useState(preset.companyCode ?? '');
  const [fiscalYear, setFiscalYear] = useState(period.fiscalYear);
  const [quarter, setQuarter] = useState(period.quarter);
  const [section, setSection] = useState(preset.section ?? '');
  const [challanNo, setChallanNo] = useState('');
  const [bsr, setBsr] = useState('');
  const [deposit, setDeposit] = useState(today());
  const [amount, setAmount] = useState(preset.differenceMinor ? (preset.differenceMinor / 100).toFixed(2) : '');
  const [note, setNote] = useState('');
  const sections = controls.data?.tds.sections ?? {};
  const company = companyCode || me.data?.attributes.company_codes?.[0] || '1000';
  const first = fyValid(fiscalYear) ? quarterStart(fiscalYear, quarter) : '';
  const problems = [
    !fyValid(fiscalYear) && 'Fiscal year looks like 2026-27',
    !section && 'Choose the TDS section the challan pays',
    !/^[0-9]{5}$/.test(challanNo) && 'The challan serial number is five digits',
    !/^[0-9]{7}$/.test(bsr) && 'The BSR code of the bank branch is seven digits',
    !deposit && 'Enter the deposit date',
    !!deposit && deposit > today() && 'The deposit date is in the future',
    !!deposit && !!first && deposit < first && `A challan for ${fiscalYear} ${quarter} is deposited on or after ${first}`,
    !isPositive(amount) && 'Enter the amount deposited in rupees',
  ].filter(Boolean) as string[];
  const save = useCommand(() => api.post<Challan>('/finance/tds-challans', {
    companyCode: company, fiscalYear, quarter, section, challanNo, bsrCode: bsr, depositDate: deposit, amountMinor: rupeesToMinor(amount), note: note.trim() || undefined,
  }), { success: (c) => `Challan ${c.challanNo} recorded for ${c.companyCode} ${c.section}`, onSuccess: onClose });
  return (
    <Dialog open title="Record TDS challan" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Company code">{(id) => <Input id={id} maxLength={10} value={companyCode || company} onChange={(e) => setCompanyCode(e.target.value.trim())} />}</Field>
        <Field label="TDS section">{(id) => <Select id={id} value={section} onChange={(e) => setSection(e.target.value)}
          options={[{ value: '', label: controls.isLoading ? 'Loading…' : 'Choose a section' },
            ...(preset.section && !sections[preset.section] ? [{ value: preset.section, label: preset.section }] : []),
            ...Object.entries(sections).map(([k, v]) => ({ value: k, label: `${k}${v.label ? ` · ${v.label}` : ''} · ${v.ratePct}%` }))]} />}</Field>
        <Field label="Fiscal year" error={fiscalYear && !fyValid(fiscalYear) ? 'Write it as 2026-27' : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} maxLength={7} value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value.trim())} />}
        </Field>
        <Field label="Quarter">{(id) => <Select id={id} value={quarter} onChange={(e) => setQuarter(e.target.value)} options={QUARTERS} />}</Field>
        <Field label="Challan serial number" hint="five digits">{(id, d) => <Input id={id} aria-describedby={d} inputMode="numeric" maxLength={5} value={challanNo} onChange={(e) => setChallanNo(e.target.value.trim())} />}</Field>
        <Field label="BSR code" hint="seven digits, the bank branch">{(id, d) => <Input id={id} aria-describedby={d} inputMode="numeric" maxLength={7} value={bsr} onChange={(e) => setBsr(e.target.value.trim())} />}</Field>
        <Field label="Deposit date">{(id) => <Input id={id} type="date" min={first || undefined} max={today()} value={deposit} onChange={(e) => setDeposit(e.target.value)} />}</Field>
        <Field label="Amount deposited (₹)">{(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}</Field>
        <div className="md:col-span-2"><Field label="Note (optional)">{(id) => <Input id={id} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />}</Field></div>
      </div>
      {problems.length > 0 && (challanNo || bsr || amount) && <p className="mt-2 text-xs text-amber-700" role="status">{problems[0]}</p>}
      <div className="mt-3"><ProblemBox error={save.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={problems.length > 0} busy={save.isPending} onClick={() => save.mutate()}>Record challan</Button>
      </div>
    </Dialog>
  );
}

function VoidChallanDialog({ challan, onClose }: { challan: Challan; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.post<Challan>(`/finance/tds-challans/${challan.id}/void`, { reason: reason.trim() }), {
    success: `Challan ${challan.challanNo} voided; ${inr(challan.amountMinor)} no longer counts as deposited`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Void challan ${challan.challanNo}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        {challan.companyCode} · {challan.section} · BSR {challan.bsrCode} · deposited {date(challan.depositDate)} · {inr(challan.amountMinor)}. A voided challan stays on record
        but is left out of the reconciliation and the Form 16A data.
      </p>
      <div className="mt-3"><Field label="Reason (at least 5 characters)" required>{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Recorded against the wrong section" />}</Field></div>
      <div className="mt-3"><ProblemBox error={save.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={reason.trim().length < 5} busy={save.isPending} onClick={() => save.mutate()}>Void challan</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Form 16A data
type Cert16A = { form: string; financialYear: string; assessmentYear: string; quarter: string; companyCode: string; certificateNo: string | null;
  deductor: { tan: string | null; pan: string | null; name: string | null }; deductee: { supplier: string; name: string; pan: string };
  section: string; sectionLabel: string | null;
  payments: { payment: string; invoice: string; dateOfPaymentCredit: string; amountPaidCreditedMinor: number; ratePct: string | null; taxDeductedMinor: number; certificate197: string | null }[];
  totals: { amountPaidCreditedMinor: number; taxDeductedMinor: number; taxDepositedMinor: number };
  challans: { bsrCode: string; challanSerialNo: string; depositDate: string; challanAmountMinor: number }[]; missingMandatory: string[] };

const MISSING_TEXT: Record<string, string> = { 'deductor.tan': "deductor's TAN", 'deductor.pan': "deductor's PAN", 'deductee.pan': "deductee's PAN" };

export function Form16ATab() {
  const [period, setPeriod] = useState(currentPeriod());
  const [supplier, setSupplier] = useState('');
  const [loaded, setLoaded] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const ok = fyValid(period.fiscalYear);
  const base = `fiscal_year=${period.fiscalYear}&quarter=${period.quarter}${supplier.trim() ? `&supplier=${encodeURIComponent(supplier.trim())}` : ''}`;
  const data = useApi<{ fiscalYear: string; quarter: string; certificates: Cert16A[]; count: number }>(loaded);
  const fileBase = `FORM16A_${period.fiscalYear}_${period.quarter}`;
  const download = (format: 'json' | 'csv') => { setError(null); downloadFile(`/finance/tds-certificates/data?${base}&format=${format}`, `${fileBase}.${format}`).catch(setError); };
  const missing = (data.data?.certificates ?? []).filter((c) => c.missingMandatory.length);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <PeriodFields value={period} onChange={(v) => { setPeriod(v); setLoaded(null); }} />
        <Field label="Supplier code (optional)">{(id) => <Input id={id} value={supplier} onChange={(e) => { setSupplier(e.target.value); setLoaded(null); }} placeholder="e.g. 100001" />}</Field>
        <div className="flex flex-wrap items-end gap-2 md:col-span-4">
          <Button variant="primary" disabled={!ok} onClick={() => setLoaded(`/finance/tds-certificates/data?${base}&format=json`)}>Show the data</Button>
          <Button disabled={!ok} onClick={() => download('json')}>Download JSON</Button>
          <Button disabled={!ok} onClick={() => download('csv')}>Download CSV</Button>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Form 16A data per deductee, company code and section for the quarter: the payments with the amount paid and the tax deducted, the challans of the section and the tax deposited
        attributable to the deductee (pro rata to the tax deducted). The certificate itself is generated and signed in TRACES from the return, which also gives its number. Every export is audited.
      </p>
      <ProblemBox error={error} />
      {loaded && (data.isLoading ? <Loading /> : data.error ? <ProblemBox error={data.error} /> : data.data && (
        <div className="space-y-3">
          <p className="text-sm">{data.data.count} certificate{data.data.count === 1 ? '' : 's'} for {data.data.fiscalYear} {data.data.quarter}
            {data.data.certificates[0] ? ` · assessment year ${data.data.certificates[0].assessmentYear}` : ''}</p>
          {missing.length > 0 && (
            <p role="status" className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {missing.length} certificate{missing.length === 1 ? ' is' : 's are'} missing mandatory data the platform does not hold:{' '}
              {[...new Set(missing.flatMap((c) => c.missingMandatory))].map((m) => MISSING_TEXT[m] ?? m).join(', ')}. The tenant publishes the deductor&apos;s TAN and PAN in rule set TDS (deductor); the deductee&apos;s PAN comes from the supplier&apos;s GSTIN.
            </p>
          )}
          {!data.data.certificates.length ? <Empty title="No TDS was deducted in this quarter" hint="A payment with TDS or a lower-deduction certificate puts the deductee here." /> : (
            <div className="space-y-2">
              {data.data.certificates.map((c) => (
                <details key={`${c.companyCode}-${c.deductee.supplier}-${c.section}`} className="rounded-lg border border-slate-200">
                  <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]">
                    <span><span className="font-medium">{c.deductee.supplier} · {c.deductee.name}</span> <span className="text-xs text-slate-500">PAN {c.deductee.pan} · {c.section}{c.sectionLabel ? ` · ${c.sectionLabel}` : ''} · company {c.companyCode}</span></span>
                    <span className="tabular-nums">paid {inr(c.totals.amountPaidCreditedMinor)} · deducted <span className="font-semibold">{inr(c.totals.taxDeductedMinor)}</span> · deposited {inr(c.totals.taxDepositedMinor)}
                      {c.missingMandatory.length > 0 && <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800 ring-1 ring-inset ring-amber-200">data missing</span>}</span>
                  </summary>
                  <div className="space-y-2 border-t border-slate-100 p-3">
                    <p className="text-xs text-slate-600">
                      Deductor {c.deductor.name ?? '–'} · TAN {c.deductor.tan ?? 'not set'} · PAN {c.deductor.pan ?? 'not set'} · certificate no. {c.certificateNo ?? 'from TRACES'}
                      {c.missingMandatory.length ? <span className="font-semibold text-amber-800"> · missing {c.missingMandatory.map((m) => MISSING_TEXT[m] ?? m).join(', ')}</span> : null}
                    </p>
                    <DataTable<Cert16A['payments'][number] & { id: string }> rows={c.payments.map((p) => ({ ...p, id: p.payment }))} caption={`Payments of ${c.deductee.supplier} ${c.section}`} columns={[
                      { key: 'payment', header: 'Payment', render: (p) => <span className="font-mono text-xs">{p.payment}</span> },
                      { key: 'invoice', header: 'Invoice' },
                      { key: 'dateOfPaymentCredit', header: 'Date of payment', render: (p) => date(p.dateOfPaymentCredit) },
                      { key: 'amountPaidCreditedMinor', header: 'Amount paid', align: 'right', render: (p) => inr(p.amountPaidCreditedMinor) },
                      { key: 'ratePct', header: 'Rate %', align: 'right', render: (p) => p.ratePct ?? '–' },
                      { key: 'taxDeductedMinor', header: 'Tax deducted', align: 'right', render: (p) => inr(p.taxDeductedMinor) },
                      { key: 'certificate197', header: 's.197', render: (p) => p.certificate197 ?? '–' },
                    ]} />
                    {c.challans.length > 0 ? (
                      <p className="text-xs text-slate-600">Challans of the section: {c.challans.map((x) => `${x.challanSerialNo} / BSR ${x.bsrCode} / ${date(x.depositDate)} / ${inr(x.challanAmountMinor)}`).join(' · ')}</p>
                    ) : <p className="text-xs text-amber-800">No challan recorded for this section and quarter: nothing is shown as deposited.</p>}
                  </div>
                </details>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- TDS register (deducted by payment) and the return export
type Register = { fiscalYear: string | null; items: { payment: string; invoice: string; supplier: string; section: string | null; ratePct: string | null; baseMinor: number; tdsMinor: number;
  valueDate: string; panOnFile: boolean }[]; totalTdsMinor: number; bySupplierSection: { supplier: string; section: string; tdsMinor: number }[] };

export function RegisterTab() {
  const [fiscalYear, setFiscalYear] = useState(currentPeriod().fiscalYear);
  const [supplier, setSupplier] = useState('');
  const ok = fyValid(fiscalYear);
  const q = `?fiscal_year=${fiscalYear}${supplier.trim() ? `&supplier=${encodeURIComponent(supplier.trim())}` : ''}`;
  const { data, isLoading, error } = useApi<Register>(ok ? `/finance/tds-register${q}` : null);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <Field label="Fiscal year" hint="e.g. 2026-27" error={fiscalYear && !ok ? 'Write it as 2026-27' : undefined}>
          {(id, d) => <Input id={id} aria-describedby={d} maxLength={7} value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value.trim())} />}
        </Field>
        <Field label="Supplier code (optional)">{(id) => <Input id={id} value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="e.g. 100087" />}</Field>
      </div>
      {!ok ? <Empty title="Enter the fiscal year as 2026-27" /> : isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="TDS withheld" value={inr(data.totalTdsMinor)} hint={`${data.items.length} payment(s) in ${data.fiscalYear ?? 'all years'}`} />
            <Kpi label="Suppliers and sections" value={data.bySupplierSection.length} />
            <Kpi label="Without PAN on file" value={new Set(data.items.filter((i) => !i.panOnFile).map((i) => i.supplier)).size} tone={data.items.some((i) => !i.panOnFile) ? 'warn' : 'good'}
              hint="deducted at the higher no-PAN rate" />
          </div>
          <DataTable<Register['items'][number] & { id: string }> rows={data.items.map((i) => ({ ...i, id: i.payment }))} empty="No TDS withheld in this fiscal year" caption="TDS register" columns={[
            { key: 'payment', header: 'Payment', render: (p) => <span className="font-mono text-xs">{p.payment}</span> },
            { key: 'invoice', header: 'Invoice' },
            { key: 'supplier', header: 'Supplier' },
            { key: 'section', header: 'Section', render: (p) => p.section ?? '–' },
            { key: 'valueDate', header: 'Value date', render: (p) => date(p.valueDate) },
            { key: 'ratePct', header: 'Rate %', align: 'right', render: (p) => p.ratePct ?? '–' },
            { key: 'baseMinor', header: 'Base', align: 'right', render: (p) => inr(p.baseMinor) },
            { key: 'tdsMinor', header: 'TDS', align: 'right', render: (p) => inr(p.tdsMinor) },
            { key: 'panOnFile', header: 'PAN', render: (p) => (p.panOnFile ? 'on file' : <span className="font-semibold text-amber-700">missing</span>) },
          ]} />
        </div>
      )}
      <TdsExportCard />
    </div>
  );
}

// ---------------------------------------------------------------- MSME interest register
type MsmeInterest = { id: string; supplier: string; invoice: string; dueDate: string; paidOn: string; daysLate: number; principalMinor: number; ratePct: string; interestMinor: number; status: string };

export function MsmeTab() {
  const [supplier, setSupplier] = useState('');
  const { data, isLoading, error } = useApi<{ items: MsmeInterest[]; totalMinor: number }>(`/finance/msme-interest${supplier.trim() ? `?supplier=${encodeURIComponent(supplier.trim())}` : ''}`);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <Field label="Supplier code (optional)">{(id) => <Input id={id} value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="e.g. 100001" />}</Field>
      </div>
      <p className="text-xs text-slate-500">
        Under the MSMED Act s.16 a buyer owes compound interest, at three times the bank rate, on a payment to a micro or small supplier made after its due date. The interest is recorded when
        the payment is made and the tenant has published the bank rate in rule set MSME; until then late payments are listed by the due-date ladder only.
      </p>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Interest accrued" value={inr(data.totalMinor)} tone={data.totalMinor ? 'warn' : 'good'} hint="cases with status accrued" />
            <Kpi label="Late payments" value={data.items.length} hint={data.items.length ? `${data.items.reduce((n, i) => n + i.daysLate, 0)} days late in total` : undefined} />
          </div>
          <DataTable<MsmeInterest> rows={data.items} empty="No interest recorded: no MSME payment was made after its due date" caption="MSME interest register" columns={[
            { key: 'supplier', header: 'Supplier' },
            { key: 'invoice', header: 'Invoice', render: (i) => <Link href={`/pic/invoices/${encodeURIComponent(i.invoice)}`} className="font-medium text-[#1A56DB] hover:underline">{i.invoice}</Link> },
            { key: 'dueDate', header: 'Due', render: (i) => date(i.dueDate) },
            { key: 'paidOn', header: 'Paid on', render: (i) => date(i.paidOn) },
            { key: 'daysLate', header: 'Days late', align: 'right' },
            { key: 'principalMinor', header: 'Principal', align: 'right', render: (i) => inr(i.principalMinor) },
            { key: 'ratePct', header: 'Rate %', align: 'right' },
            { key: 'interestMinor', header: 'Interest', align: 'right', render: (i) => <span className="font-semibold">{inr(i.interestMinor)}</span> },
            { key: 'status', header: 'Status', render: (i) => <StatusChip status={i.status} /> },
          ]} />
          <p className="text-xs text-slate-500">Newest payment first, at most 500 cases.</p>
        </div>
      )}
    </div>
  );
}
