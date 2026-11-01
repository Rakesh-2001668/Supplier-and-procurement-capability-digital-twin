'use client';

// Pending workflow 26: supplier rebates on a contract (volume or value tiers, accrual from posted invoices, settlement as an ERP credit memo).

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, isNumber, useSessionUser } from '../../invoices/_components';

type Tier = { from: string; ratePct: string };
type Settlement = { number: string; amount_minor: number; status: string; erp_document: string | null; posted_at: string | null };
type Accrual = {
  id: string; period_label: string; period_start: string; period_end: string; basis_value_minor: number; basis_qty: string; rate_pct: string;
  accrued_minor: number; status: string; computed_at: string; settlement: Settlement | null; settleable: boolean;
  detail: { invoices?: number; creditedMinor?: number; tiers?: { tierFrom: string; ratePct: string; applied?: string; partOfBasis?: string; amountMinor?: number }[] };
};
type Rebate = {
  id: string; number: string; title: string; basis: 'VOLUME' | 'VALUE'; period: string; tier_mode: string; scope: string; tiers: Tier[]; valid_from: string;
  valid_to: string; status: string; accruals: Accrual[]; accruedOpenMinor: number; settledMinor: number;
};

export function RebatesTab({ contractNumber, contractType, contractStatus, validFrom, validTo, canManage }: {
  contractNumber: string; contractType: string; contractStatus: string; validFrom: string; validTo: string; canManage: boolean;
}) {
  const { data, isLoading, error } = useApi<Rebate[]>(`/contracts/${encodeURIComponent(contractNumber)}/rebates`);
  const [open, setOpen] = useState(false);
  const closed = ['TERMINATED', 'EXPIRED', 'RENEWED'].includes(contractStatus);
  const allowed = canManage && contractType !== 'NDA' && !closed;
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-3xl text-sm text-slate-600">
          A rebate pays back a share of what is bought from the supplier once volume or value tiers are reached. It accrues from posted invoices net of credit notes; after the period ends it is settled
          as a vendor credit memo posted to the ERP once.
          {contractType === 'NDA' && ' An NDA carries no purchases and so no rebate.'}
        </p>
        {allowed && <Button variant="primary" onClick={() => setOpen(true)}>New rebate agreement</Button>}
      </div>
      {!data?.length ? <Empty title="No rebate agreements" hint={allowed ? 'Create one to start accruing.' : undefined} /> : data.map((r) => <RebateCard key={r.id} rebate={r} canManage={canManage} />)}
      {open && <CreateRebateDialog contractNumber={contractNumber} contractType={contractType} validFrom={validFrom} validTo={validTo} onClose={() => setOpen(false)} />}
    </div>
  );
}

function RebateCard({ rebate: r, canManage }: { rebate: Rebate; canManage: boolean }) {
  const user = useSessionUser();
  const canSettle = hasRole(user, 'FINANCE_CONTROLLER', 'CONTRACT_MANAGER');
  const [cancelling, setCancelling] = useState(false);
  const accrue = useCommand(() => api.post(`/rebates/${encodeURIComponent(r.number)}/accrue`), { success: 'Accrual recomputed from posted invoices' });
  const settle = useCommand((id: string) => api.post(`/rebate-accruals/${id}/settle`), { success: 'Settled – credit memo sent to the ERP' });
  const measure = r.basis === 'VALUE' ? 'purchase value (₹)' : 'purchased quantity';
  return (
    <Card title={<span>{r.number} <span className="font-normal text-slate-500">{r.title}</span> <StatusChip status={r.status} /></span>}
      actions={canManage && r.status === 'ACTIVE' ? (
        <>
          <Button busy={accrue.isPending} onClick={() => accrue.mutate()}>Recompute accrual</Button>
          <Button variant="danger" onClick={() => setCancelling(true)}>Cancel agreement</Button>
        </>
      ) : undefined}>
      <div className="space-y-4">
        <Facts items={[
          ['Basis', label(r.basis)], ['Period', label(r.period)], ['Tiers apply', r.tier_mode === 'SLAB' ? 'Slab – each tier on its own part' : 'Retroactive – whole period at the tier reached'],
          ['Scope', r.scope === 'CONTRACT' ? 'This contract’s lines' : 'All purchases from the supplier'], ['Valid', `${date(r.valid_from)} – ${date(r.valid_to)}`],
          ['Accrued, unsettled', inr(r.accruedOpenMinor)], ['Settled', inr(r.settledMinor)],
        ]} />
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Tiers on {measure}</p>
          <DataTable<Tier & Record<string, unknown>> rows={r.tiers} columns={[
            { key: 'from', header: r.basis === 'VALUE' ? 'From (₹)' : 'From (quantity)', align: 'right', render: (t) => qty(t.from) },
            { key: 'ratePct', header: 'Rebate %', align: 'right', render: (t) => `${t.ratePct}%` },
          ]} />
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Accruals and settlement</p>
          <DataTable<Accrual & Record<string, unknown>> rows={r.accruals} empty="Nothing accrued yet" columns={[
            { key: 'period_label', header: 'Period', render: (a) => <span title={`${date(a.period_start)} – ${date(a.period_end)}`}>{a.period_label}</span> },
            { key: 'basis_value_minor', header: 'Purchases net of credits', align: 'right', render: (a) => <span title={a.detail?.invoices != null ? `${a.detail.invoices} invoice(s), credited ${inr(a.detail.creditedMinor)}` : undefined}>{inr(a.basis_value_minor)}</span> },
            { key: 'basis_qty', header: 'Quantity', align: 'right', render: (a) => qty(a.basis_qty) },
            { key: 'rate_pct', header: 'Effective rate', align: 'right', render: (a) => `${a.rate_pct}%` },
            { key: 'accrued_minor', header: 'Accrued', align: 'right', render: (a) => <span className="font-semibold">{inr(a.accrued_minor)}</span> },
            { key: 'status', header: 'Status', render: (a) => <StatusChip status={a.status === 'SETTLED' ? 'COMPLETED' : 'OPEN'} /> },
            { key: 'settlement', header: 'Credit memo', render: (a) => (a.settlement
              ? <span>{a.settlement.number} · <StatusChip status={a.settlement.status === 'POSTED' ? 'POSTED' : 'PENDING'} />{a.settlement.erp_document ? ` ERP ${a.settlement.erp_document}` : ''}</span> : '–') },
            { key: 'action', header: '', render: (a) => (canSettle && a.settleable
              ? <Button variant="primary" busy={settle.isPending} onClick={() => settle.mutate(a.id)}>Settle</Button>
              : a.status === 'OPEN' && a.accrued_minor > 0 ? <span className="text-xs text-slate-500">settles after {date(a.period_end)}</span> : null) },
          ]} />
          <p className="mt-1 text-xs text-slate-500">Last computed {dateTime(r.accruals[0]?.computed_at)}. GST treatment of a rebate credit note is for Finance and Tax to confirm before settlement.</p>
        </div>
        <ProblemBox error={settle.error ?? accrue.error} />
      </div>
      {cancelling && <CancelDialog rebate={r} onClose={() => setCancelling(false)} />}
    </Card>
  );
}

function CancelDialog({ rebate, onClose }: { rebate: Rebate; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cancel = useCommand(() => api.post(`/rebates/${encodeURIComponent(rebate.number)}/cancel`, { reason: reason.trim() }), { success: `${rebate.number} cancelled`, onSuccess: onClose });
  return (
    <Dialog open title={`Cancel ${rebate.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Only an agreement without an unsettled accrual can be cancelled. Settle or let the accrued periods go through first.</p>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="mt-3"><ProblemBox error={cancel.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Keep</Button>
        <Button variant="danger" busy={cancel.isPending} disabled={!reason.trim()} onClick={() => cancel.mutate()}>Cancel agreement</Button>
      </div>
    </Dialog>
  );
}

function CreateRebateDialog({ contractNumber, contractType, validFrom, validTo, onClose }: {
  contractNumber: string; contractType: string; validFrom: string; validTo: string; onClose: () => void;
}) {
  const master = contractType === 'MASTER_AGREEMENT';
  const [idempotencyKey] = useState(() => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`));
  const [f, setF] = useState({ title: '', basis: 'VALUE', period: 'QUARTERLY', tier_mode: 'RETROACTIVE', scope: master ? 'SUPPLIER' : 'CONTRACT', valid_from: validFrom, valid_to: validTo });
  const [tiers, setTiers] = useState<Tier[]>([{ from: '0', ratePct: '' }]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const updateTier = (i: number, patch: Partial<Tier>) => setTiers((ts) => ts.map((t, j) => (j === i ? { ...t, ...patch } : t)));

  const rising = tiers.every((t, i) => i === 0 || (Number(t.from) > Number(tiers[i - 1].from) && Number(t.ratePct) >= Number(tiers[i - 1].ratePct)));
  const tiersOk = tiers.every((t) => isNumber(t.from) && Number(t.from) >= 0 && isNumber(t.ratePct) && Number(t.ratePct) > 0 && Number(t.ratePct) <= 100) && rising;
  const valid = f.title.trim().length >= 3 && tiersOk && f.valid_from && f.valid_to && f.valid_to >= f.valid_from;

  const create = useCommand(() => api.post<{ number: string }>(`/contracts/${encodeURIComponent(contractNumber)}/rebates`, {
    title: f.title.trim(), basis: f.basis, period: f.period, tier_mode: f.tier_mode, scope: f.scope, valid_from: f.valid_from, valid_to: f.valid_to,
    tiers: tiers.map((t) => ({ from: t.from.trim(), ratePct: t.ratePct.trim() })),
  }, { idempotencyKey }), { success: (r) => `${r.number} created and accruing`, onSuccess: onClose });

  return (
    <Dialog open title={`New rebate agreement · ${contractNumber}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2"><Field label="Title *">{(id) => <Input id={id} value={f.title} onChange={set('title')} placeholder="e.g. Annual volume rebate FY27" />}</Field></div>
        <Field label="Basis">{(id) => <Select id={id} value={f.basis} onChange={set('basis')} options={[{ value: 'VALUE', label: 'Purchase value (₹)' }, { value: 'VOLUME', label: 'Purchased quantity' }]} />}</Field>
        <Field label="Period" hint="Quarters follow the Indian fiscal year (April–March)">{(id) => <Select id={id} value={f.period} onChange={set('period')} options={[{ value: 'MONTHLY', label: 'Monthly' }, { value: 'QUARTERLY', label: 'Quarterly' }, { value: 'ANNUAL', label: 'Annual' }]} />}</Field>
        <Field label="How tiers apply" hint="Retroactive: the tier reached applies to the whole period. Slab: each tier to its own part.">
          {(id) => <Select id={id} value={f.tier_mode} onChange={set('tier_mode')} options={[{ value: 'RETROACTIVE', label: 'Retroactive' }, { value: 'SLAB', label: 'Slab' }]} />}
        </Field>
        <Field label="Purchases counted" hint={master ? 'A master agreement has no lines: all purchases from the supplier' : undefined}>
          {(id) => <Select id={id} value={f.scope} disabled={master} onChange={set('scope')} options={[{ value: 'CONTRACT', label: 'This contract’s lines' }, { value: 'SUPPLIER', label: 'All purchases from the supplier' }]} />}
        </Field>
        <Field label="Valid from">{(id) => <Input id={id} type="date" value={f.valid_from} onChange={set('valid_from')} />}</Field>
        <Field label="Valid to">{(id) => <Input id={id} type="date" value={f.valid_to} onChange={set('valid_to')} />}</Field>
      </div>
      <div className="mt-4">
        <div className="mb-1 flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tiers ({f.basis === 'VALUE' ? 'from ₹' : 'from quantity'})</p>
          <Button type="button" onClick={() => setTiers((ts) => [...ts, { from: '', ratePct: '' }])}>Add tier</Button>
        </div>
        <div className="space-y-2">
          {tiers.map((t, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
              <Field label={`Tier ${i + 1} starts at`}>{(id) => <Input id={id} inputMode="decimal" value={t.from} onChange={(e) => updateTier(i, { from: e.target.value })} />}</Field>
              <Field label="Rebate %">{(id) => <Input id={id} inputMode="decimal" value={t.ratePct} onChange={(e) => updateTier(i, { ratePct: e.target.value })} />}</Field>
              {tiers.length > 1 ? <Button type="button" variant="ghost" onClick={() => setTiers((ts) => ts.filter((_, j) => j !== i))}>Remove</Button> : <span />}
            </div>
          ))}
        </div>
        {!rising && <p className="mt-1 text-xs text-red-700">Thresholds must rise, and a higher tier cannot pay a lower rate.</p>}
      </div>
      <div className="mt-3"><ProblemBox error={create.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={create.isPending} disabled={!valid} onClick={() => create.mutate()}>Create agreement</Button>
      </div>
    </Dialog>
  );
}
