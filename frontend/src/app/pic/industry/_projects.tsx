'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Field, Input, Kpi, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Advance = { id: string; number: string; po: string; status: string; net_minor: number; gross_minor: number; recovery_pct: string; recovered_minor: number;
  balanceMinor: number; plannedMinor: number; guarantee: string | null; document: string | null; reference: string };
type Guarantee = { id: string; number: string; kind: string; po: string; bank_name: string; bank_ref: string; amount_minor: number; issue_date: string;
  expiry_date: string; status: string; daysToExpiry: number; valid: boolean; expiringSoon: boolean; version: number };
type Licence = { id: string; number: string; supplier: string; product: string; metric: string; entitled_qty: string; peak_used_qty: string | null; utilisation_pct: string | null;
  unused_qty: string | null; potential_saving_minor: number | null; term_end: string; daysToRenewal: number; flag: string | null; status: string };
type LicenceSummary = { licences: Licence[]; flagged: number; potentialSavingMinor: number; yearlyCostMinor: number };

/** Advance payment against a subcontract (BP §23 Construction): requested, approved by finance, recovered pro rata from running bills. */
export function AdvancePanel({ canRequest }: { canRequest: boolean }) {
  const advances = useApi<Advance[]>('/advances');
  const [form, setForm] = useState({ po: '', netRupees: '', reference: '', reason: '' });
  const request = useCommand(() => api.post<Advance>(`/purchase-orders/${encodeURIComponent(form.po.trim())}/advances`,
    { netMinor: Math.round(Number(form.netRupees) * 100), reference: form.reference.trim(), reason: form.reason.trim() || null }),
    { success: (a) => `${a.number} requested: finance approves it from the task inbox` });
  return (
    <Card title="Advance payments and recovery">
      {canRequest && (
        <form onSubmit={(e) => { e.preventDefault(); request.mutate(); }} className="mb-4 grid gap-3 md:grid-cols-5 md:items-end">
          <Field label="Purchase order">{(id) => <Input id={id} required value={form.po} onChange={(e) => setForm({ ...form, po: e.target.value })} />}</Field>
          <Field label="Advance (₹, before GST)">{(id) => <Input id={id} required type="number" min="1" step="0.01" value={form.netRupees} onChange={(e) => setForm({ ...form, netRupees: e.target.value })} />}</Field>
          <Field label="Contractor advance invoice">{(id) => <Input id={id} required minLength={2} value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />}</Field>
          <Field label="Reason">{(id) => <Input id={id} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />}</Field>
          <Button type="submit" variant="primary" busy={request.isPending}>Request advance</Button>
        </form>
      )}
      <DataTable<Advance>
        rows={advances.data ?? []} loading={advances.isLoading} error={advances.error} empty="No advances"
        columns={[
          { key: 'number', header: 'Advance', render: (a) => <span className="font-medium">{a.number}</span> },
          { key: 'po', header: 'Order' },
          { key: 'status', header: 'Status', render: (a) => <StatusChip status={a.status} /> },
          { key: 'gross_minor', header: 'Advance (incl. GST)', align: 'right', render: (a) => inr(a.gross_minor) },
          { key: 'recovery_pct', header: 'Recovered per bill', align: 'right', render: (a) => `${Number(a.recovery_pct)}%` },
          { key: 'recovered_minor', header: 'Recovered', align: 'right', render: (a) => inr(a.recovered_minor) },
          { key: 'balanceMinor', header: 'Balance', align: 'right', render: (a) => inr(a.balanceMinor) },
          { key: 'guarantee', header: 'Guarantee', render: (a) => a.guarantee ?? '–' },
          { key: 'document', header: 'AP document', render: (a) => a.document ?? '–' },
        ]}
      />
    </Card>
  );
}

/** Bank guarantee register: record, verify (a second person), alerts before expiry, release. */
export function GuaranteePanel({ scopes }: { scopes: string[] }) {
  const list = useApi<Guarantee[]>('/bank-guarantees');
  const canRecord = scopes.includes('contract:manage');
  const canVerify = scopes.includes('payment:run');
  const [form, setForm] = useState({ po: '', kind: 'PERFORMANCE', bankName: '', bankRef: '', amountRupees: '', issueDate: '', expiryDate: '' });
  const record = useCommand(() => api.post<Guarantee>('/bank-guarantees', { po: form.po.trim(), kind: form.kind, bankName: form.bankName.trim(), bankRef: form.bankRef.trim(),
    amountMinor: Math.round(Number(form.amountRupees) * 100), issueDate: form.issueDate, expiryDate: form.expiryDate }), { success: (g) => `${g.number} recorded: finance verifies it with the bank` });
  const act = useCommand((a: { g: Guarantee; action: 'verify' | 'release' }) => api.post(`/bank-guarantees/${a.g.number}/${a.action}`,
    a.action === 'verify' ? { reason: 'Confirmed with the issuing bank' } : { reason: window.prompt('Release reason') || '' }, { ifMatch: `"${a.g.version}"` }),
    { success: 'Guarantee updated' });
  const soon = (list.data ?? []).filter((g) => g.expiringSoon).length;
  return (
    <Card title="Bank guarantees">
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Kpi label="Active" value={(list.data ?? []).filter((g) => g.status === 'ACTIVE').length} />
        <Kpi label="Expiring within 60 days" value={soon} tone={soon ? 'warn' : 'good'} />
        <Kpi label="Awaiting verification" value={(list.data ?? []).filter((g) => g.status === 'PENDING_VERIFICATION').length} />
      </div>
      {canRecord && (
        <form onSubmit={(e) => { e.preventDefault(); record.mutate(); }} className="mb-4 grid gap-3 md:grid-cols-4 md:items-end">
          <Field label="Purchase order">{(id) => <Input id={id} required value={form.po} onChange={(e) => setForm({ ...form, po: e.target.value })} />}</Field>
          <Field label="Kind">{(id) => <Select id={id} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} options={[{ value: 'PERFORMANCE', label: 'Performance' }, { value: 'ADVANCE', label: 'Advance' }]} />}</Field>
          <Field label="Bank">{(id) => <Input id={id} required value={form.bankName} onChange={(e) => setForm({ ...form, bankName: e.target.value })} />}</Field>
          <Field label="Guarantee number">{(id) => <Input id={id} required value={form.bankRef} onChange={(e) => setForm({ ...form, bankRef: e.target.value })} />}</Field>
          <Field label="Amount (₹)">{(id) => <Input id={id} required type="number" min="1" step="0.01" value={form.amountRupees} onChange={(e) => setForm({ ...form, amountRupees: e.target.value })} />}</Field>
          <Field label="Issued">{(id) => <Input id={id} required type="date" value={form.issueDate} onChange={(e) => setForm({ ...form, issueDate: e.target.value })} />}</Field>
          <Field label="Expires">{(id) => <Input id={id} required type="date" value={form.expiryDate} onChange={(e) => setForm({ ...form, expiryDate: e.target.value })} />}</Field>
          <Button type="submit" variant="primary" busy={record.isPending}>Record guarantee</Button>
        </form>
      )}
      <DataTable<Guarantee>
        rows={list.data ?? []} loading={list.isLoading} error={list.error} empty="No bank guarantees"
        columns={[
          { key: 'number', header: 'Guarantee', render: (g) => <span className="font-medium">{g.number}</span> },
          { key: 'kind', header: 'Kind' },
          { key: 'po', header: 'Order' },
          { key: 'bank_name', header: 'Bank', render: (g) => `${g.bank_name} · ${g.bank_ref}` },
          { key: 'amount_minor', header: 'Amount', align: 'right', render: (g) => inr(g.amount_minor) },
          { key: 'expiry_date', header: 'Expires', render: (g) => `${date(g.expiry_date)}${g.status === 'ACTIVE' ? ` (${g.daysToExpiry} d)` : ''}` },
          { key: 'status', header: 'Status', render: (g) => <StatusChip status={g.status} /> },
          { key: 'actions', header: 'Actions', render: (g) => (
            <div className="flex gap-1.5">
              {canVerify && g.status === 'PENDING_VERIFICATION' && <Button variant="primary" onClick={() => act.mutate({ g, action: 'verify' })}>Verify</Button>}
              {(canVerify || canRecord) && g.status === 'ACTIVE' && <Button onClick={() => act.mutate({ g, action: 'release' })}>Release</Button>}
            </div>
          ) },
        ]}
      />
    </Card>
  );
}

/** Licence entitlements and usage (BP §23 IT services): the unused-licence flag raised before the renewal alert. */
export function LicencePanel({ canManage }: { canManage: boolean }) {
  const list = useApi<LicenceSummary>('/licences');
  const [form, setForm] = useState({ supplier: '', product: '', entitledQty: '', unitRupees: '', termStart: '', termEnd: '' });
  const [usage, setUsage] = useState({ licence: '', asOf: '', usedQty: '' });
  const create = useCommand(() => api.post('/licences', { supplier: form.supplier.trim(), product: form.product.trim(), entitledQty: Number(form.entitledQty),
    unitPriceMinor: Math.round(Number(form.unitRupees) * 100), termStart: form.termStart, termEnd: form.termEnd }), { success: 'Entitlement created' });
  const record = useCommand(() => api.post('/licences/usage', { records: [{ licence: usage.licence.trim(), asOf: usage.asOf, usedQty: Number(usage.usedQty) }], source: 'MANUAL' }),
    { success: 'Usage recorded' });
  return (
    <Card title="Licence entitlements and utilisation">
      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <Kpi label="Yearly licence cost" value={inr(list.data?.yearlyCostMinor ?? 0)} />
        <Kpi label="Flagged unused" value={list.data?.flagged ?? 0} tone={list.data?.flagged ? 'warn' : 'good'} />
        <Kpi label="Potential saving per year" value={inr(list.data?.potentialSavingMinor ?? 0)} />
      </div>
      {canManage && (
        <div className="mb-4 grid gap-4 md:grid-cols-2">
          <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="grid gap-3 md:grid-cols-3 md:items-end">
            <Field label="Supplier">{(id) => <Input id={id} required value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} />}</Field>
            <Field label="Product">{(id) => <Input id={id} required value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} />}</Field>
            <Field label="Licences">{(id) => <Input id={id} required type="number" min="1" value={form.entitledQty} onChange={(e) => setForm({ ...form, entitledQty: e.target.value })} />}</Field>
            <Field label="Price per licence per year (₹)">{(id) => <Input id={id} required type="number" min="0" step="0.01" value={form.unitRupees} onChange={(e) => setForm({ ...form, unitRupees: e.target.value })} />}</Field>
            <Field label="Term start">{(id) => <Input id={id} required type="date" value={form.termStart} onChange={(e) => setForm({ ...form, termStart: e.target.value })} />}</Field>
            <Field label="Renewal date">{(id) => <Input id={id} required type="date" value={form.termEnd} onChange={(e) => setForm({ ...form, termEnd: e.target.value })} />}</Field>
            <Button type="submit" variant="primary" busy={create.isPending}>Add entitlement</Button>
          </form>
          <form onSubmit={(e) => { e.preventDefault(); record.mutate(); }} className="grid gap-3 md:grid-cols-3 md:items-end">
            <Field label="Licence">{(id) => <Input id={id} required placeholder="LIC-1001" value={usage.licence} onChange={(e) => setUsage({ ...usage, licence: e.target.value })} />}</Field>
            <Field label="As of">{(id) => <Input id={id} required type="date" value={usage.asOf} onChange={(e) => setUsage({ ...usage, asOf: e.target.value })} />}</Field>
            <Field label="Licences in use">{(id) => <Input id={id} required type="number" min="0" value={usage.usedQty} onChange={(e) => setUsage({ ...usage, usedQty: e.target.value })} />}</Field>
            <Button type="submit" busy={record.isPending}>Record usage</Button>
            <p className="text-xs text-slate-500 md:col-span-3">Bulk usage reports are imported through POST /v1/licences/usage; re-importing a date replaces it.</p>
          </form>
        </div>
      )}
      <DataTable<Licence>
        rows={list.data?.licences ?? []} loading={list.isLoading} error={list.error} empty="No licence entitlements"
        columns={[
          { key: 'number', header: 'Licence', render: (l) => <span className="font-medium">{l.number}</span> },
          { key: 'product', header: 'Product', render: (l) => `${l.product} · ${l.supplier}` },
          { key: 'entitled_qty', header: 'Entitled', align: 'right', render: (l) => qty(l.entitled_qty) },
          { key: 'peak_used_qty', header: 'Peak use', align: 'right', render: (l) => l.peak_used_qty ? qty(l.peak_used_qty) : '–' },
          { key: 'utilisation_pct', header: 'Utilisation', align: 'right', render: (l) => l.utilisation_pct ? `${Number(l.utilisation_pct)}%` : '–' },
          { key: 'potential_saving_minor', header: 'Saving / year', align: 'right', render: (l) => l.flag ? inr(l.potential_saving_minor ?? 0) : '–' },
          { key: 'term_end', header: 'Renewal', render: (l) => `${date(l.term_end)} (${l.daysToRenewal} d)` },
          { key: 'flag', header: 'Flag', render: (l) => l.flag ? <StatusChip status="UNUSED" /> : '–' },
        ]}
      />
    </Card>
  );
}
