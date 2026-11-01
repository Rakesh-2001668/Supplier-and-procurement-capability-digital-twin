'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Field, Input, Kpi, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Charge = { id: string; number: string; po: string; line: number; carrier: string; charge_type: string; units: string; free_units: string; billable_units: string;
  rate_minor: number; amount_minor: number; status: string; reason: string | null; pod: string | null; serviceEntry: string | null; occurred_on: string };
type Rate = { id: string; supplier: string | null; lane: string | null; charge_type: string; unit: string; free_units: string; rate_minor: number; valid_from: string };
type IndexSeries = { index: string; latest: string | null; values: { id: string; as_of: string; value: string; source: string }[] };
type Reading = { id: string; object_ref: string; material: string; logger_id: string; min_seen_c: string; max_seen_c: string; excursion_minutes: number; status: string;
  quarantined_qty: string; disposition_note: string | null };
type Spec = { id: string; material: string; description: string; min_c: string; max_c: string; max_excursion_minutes: number | null; label: string | null };
type Expired = { material: string; description: string; plant: string; storageLocation: string; batch: string; qty: string; expiry: string; valueMinor: number };
type Par = { id: string; plant: string; storage_location: string; material: string; description: string; par_qty: string; trigger_qty: string; onHand: string; onOrder: string; belowTrigger: boolean };
type Vac = { periodDays: number; items: { plant: string; storageLocation: string; material: string; usedQty: string; daysOfSupply: string | null; stockOutRisk: boolean; expiringQty: string;
  suggestedPar: string | null; parAdvice: string; parQty: string }[]; totals: { valueOnHandMinor: number; expiringValueMinor: number; belowTrigger: number } };
type PCard = { id: string; number: string; holder_name: string; issuer: string; card_last4: string; per_txn_limit_minor: number; monthly_limit_minor: number; status: string;
  monthToDateMinor: number; utilisationPct: number; blocked_mccs: string[]; version: number };
type Statement = { id: string; number: string; issuer: string; period: string; status: string; line_count: number; total_minor: number };

/** Accessorial claims (detention, demurrage, loading) with proof of delivery, and the rate rules per carrier and lane. */
export function AccessorialPanel({ scopes }: { scopes: string[] }) {
  const charges = useApi<Charge[]>('/accessorial/charges');
  const rates = useApi<Rate[]>('/accessorial/rates');
  const [claim, setClaim] = useState({ po: '', line: '20', chargeType: 'DETENTION', units: '', occurredOn: '', lane: '', pod: '' });
  const [rate, setRate] = useState({ chargeType: 'DETENTION', rateRupees: '', freeUnits: '0', supplier: '', lane: '' });
  const submit = useCommand(() => api.post<Charge>(`/purchase-orders/${encodeURIComponent(claim.po.trim())}/accessorial-charges`, {
    line: Number(claim.line), chargeType: claim.chargeType, units: Number(claim.units), occurredOn: claim.occurredOn, lane: claim.lane.trim() || null,
    podServiceEntry: claim.pod.trim() || null }), { success: (c) => `${c.number}: ${label(c.status)}` });
  const addRate = useCommand(() => api.post('/accessorial/rates', { chargeType: rate.chargeType, rateMinor: Math.round(Number(rate.rateRupees) * 100), unit: 'HOUR',
    freeUnits: Number(rate.freeUnits), supplier: rate.supplier.trim() || null, lane: rate.lane.trim() || null }), { success: 'Rate rule added' });
  const canClaim = scopes.includes('ses:create') || scopes.includes('po:change') || scopes.includes('contract:manage');
  return (
    <Card title="Detention, demurrage and accessorial charges">
      {canClaim && (
        <form onSubmit={(e) => { e.preventDefault(); submit.mutate(); }} className="mb-4 grid gap-3 md:grid-cols-4 md:items-end">
          <Field label="Freight order">{(id) => <Input id={id} required value={claim.po} onChange={(e) => setClaim({ ...claim, po: e.target.value })} />}</Field>
          <Field label="Accessorial line">{(id) => <Input id={id} required type="number" min="1" value={claim.line} onChange={(e) => setClaim({ ...claim, line: e.target.value })} />}</Field>
          <Field label="Charge">{(id) => <Select id={id} value={claim.chargeType} onChange={(e) => setClaim({ ...claim, chargeType: e.target.value })}
            options={['DETENTION', 'DEMURRAGE', 'LOADING', 'UNLOADING', 'WAITING'].map((v) => ({ value: v, label: label(v) }))} />}</Field>
          <Field label="Hours / units">{(id) => <Input id={id} required type="number" min="0.01" step="any" value={claim.units} onChange={(e) => setClaim({ ...claim, units: e.target.value })} />}</Field>
          <Field label="Date">{(id) => <Input id={id} required type="date" value={claim.occurredOn} onChange={(e) => setClaim({ ...claim, occurredOn: e.target.value })} />}</Field>
          <Field label="Lane">{(id) => <Input id={id} value={claim.lane} onChange={(e) => setClaim({ ...claim, lane: e.target.value })} />}</Field>
          <Field label="Proof of delivery (service entry)" hint="Required by the freight-audit rule">{(id) => <Input id={id} value={claim.pod} onChange={(e) => setClaim({ ...claim, pod: e.target.value })} />}</Field>
          <Button type="submit" variant="primary" busy={submit.isPending}>File claim</Button>
        </form>
      )}
      <DataTable<Charge>
        rows={charges.data ?? []} loading={charges.isLoading} error={charges.error} empty="No accessorial claims"
        columns={[
          { key: 'number', header: 'Claim', render: (c) => <span className="font-medium">{c.number}</span> },
          { key: 'po', header: 'Order / line', render: (c) => `${c.po} / ${c.line}` },
          { key: 'charge_type', header: 'Charge', render: (c) => label(c.charge_type) },
          { key: 'units', header: 'Claimed → billable', align: 'right', render: (c) => `${qty(c.units)} → ${qty(c.billable_units)}` },
          { key: 'amount_minor', header: 'Amount', align: 'right', render: (c) => inr(c.amount_minor) },
          { key: 'pod', header: 'POD', render: (c) => c.pod ?? 'missing' },
          { key: 'serviceEntry', header: 'Service entry', render: (c) => c.serviceEntry ?? '–' },
          { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
          { key: 'reason', header: 'Note', render: (c) => c.reason ?? '' },
        ]}
      />
      <h3 className="mb-2 mt-6 text-sm font-semibold">Rate rules</h3>
      {scopes.includes('contract:manage') && (
        <form onSubmit={(e) => { e.preventDefault(); addRate.mutate(); }} className="mb-3 grid gap-3 md:grid-cols-6 md:items-end">
          <Field label="Charge">{(id) => <Select id={id} value={rate.chargeType} onChange={(e) => setRate({ ...rate, chargeType: e.target.value })}
            options={['DETENTION', 'DEMURRAGE', 'LOADING', 'UNLOADING', 'WAITING'].map((v) => ({ value: v, label: label(v) }))} />}</Field>
          <Field label="Rate per hour (₹)">{(id) => <Input id={id} required type="number" min="0" step="0.01" value={rate.rateRupees} onChange={(e) => setRate({ ...rate, rateRupees: e.target.value })} />}</Field>
          <Field label="Free hours">{(id) => <Input id={id} type="number" min="0" step="any" value={rate.freeUnits} onChange={(e) => setRate({ ...rate, freeUnits: e.target.value })} />}</Field>
          <Field label="Carrier (blank: all)">{(id) => <Input id={id} value={rate.supplier} onChange={(e) => setRate({ ...rate, supplier: e.target.value })} />}</Field>
          <Field label="Lane (blank: all)">{(id) => <Input id={id} value={rate.lane} onChange={(e) => setRate({ ...rate, lane: e.target.value })} />}</Field>
          <Button type="submit" busy={addRate.isPending}>Add rule</Button>
        </form>
      )}
      <DataTable<Rate>
        rows={rates.data ?? []} loading={rates.isLoading} error={rates.error} empty="No rate rules"
        columns={[{ key: 'charge_type', header: 'Charge', render: (r) => label(r.charge_type) }, { key: 'supplier', header: 'Carrier', render: (r) => r.supplier ?? 'all' },
          { key: 'lane', header: 'Lane', render: (r) => r.lane ?? 'all' }, { key: 'free_units', header: 'Free', align: 'right', render: (r) => `${qty(r.free_units)} ${r.unit.toLowerCase()}` },
          { key: 'rate_minor', header: 'Rate', align: 'right', render: (r) => inr(r.rate_minor) }, { key: 'valid_from', header: 'From', render: (r) => date(r.valid_from) }]}
      />
    </Card>
  );
}

/** Index feed (fuel and commodity indices) that contract index resets read. */
export function IndexPanel({ canFeed }: { canFeed: boolean }) {
  const [code, setCode] = useState('DIESEL_IN');
  const series = useApi<IndexSeries>(`/indices/${encodeURIComponent(code)}?limit=12`);
  const [entry, setEntry] = useState({ asOf: '', value: '' });
  const feed = useCommand(() => api.put(`/indices/${encodeURIComponent(code)}/values`, { values: [{ asOf: entry.asOf, value: entry.value }], source: 'MANUAL' }), { success: 'Index value saved' });
  return (
    <Card title="Index feed">
      <div className="mb-3 grid gap-3 md:grid-cols-4 md:items-end">
        <Field label="Index">{(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />}</Field>
        {canFeed && (<>
          <Field label="As of">{(id) => <Input id={id} type="date" value={entry.asOf} onChange={(e) => setEntry({ ...entry, asOf: e.target.value })} />}</Field>
          <Field label="Value">{(id) => <Input id={id} type="number" min="0" step="any" value={entry.value} onChange={(e) => setEntry({ ...entry, value: e.target.value })} />}</Field>
          <Button busy={feed.isPending} disabled={!entry.asOf || !entry.value} onClick={() => feed.mutate()}>Save value</Button>
        </>)}
      </div>
      <p className="mb-2 text-xs text-slate-500">Values are fed by import or API from the published source; a contract index reset takes the latest value on or before its effective date.</p>
      <DataTable<IndexSeries['values'][number]>
        rows={series.data?.values ?? []} loading={series.isLoading} error={series.error} empty="No values fed for this index"
        columns={[{ key: 'as_of', header: 'As of', render: (v) => date(v.as_of) }, { key: 'value', header: 'Value', align: 'right' }, { key: 'source', header: 'Source' }]}
      />
    </Card>
  );
}

/** Cold-chain specs and logger readings, quarantine decisions, and the expiry write-off. */
export function ColdChainPanel({ scopes }: { scopes: string[] }) {
  const readings = useApi<Reading[]>('/cold-chain/readings');
  const specs = useApi<Spec[]>('/cold-chain/specs');
  const expired = useApi<Expired[]>('/expiry/stock');
  const canSpec = scopes.includes('quality:decide') || scopes.includes('mrp:plan');
  const [spec, setSpec] = useState({ material: '', minC: '2', maxC: '8', minutes: '30' });
  const [reading, setReading] = useState({ objectType: 'GOODS_RECEIPT', ref: '', material: '', loggerId: '', csv: '' });
  const saveSpec = useCommand(() => api.put(`/materials/${encodeURIComponent(spec.material.trim())}/cold-chain-spec`, { minC: Number(spec.minC), maxC: Number(spec.maxC),
    maxExcursionMinutes: Number(spec.minutes) }), { success: 'Temperature range saved' });
  const parse = () => reading.csv.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const [at, t] = l.split(','); return { at: at.trim(), tempC: Number(t) }; });
  const send = useCommand(() => api.post<Reading>('/cold-chain/readings', { objectType: reading.objectType, ref: reading.ref.trim(), material: reading.material.trim(),
    loggerId: reading.loggerId.trim(), readings: parse() }), { success: (r) => r.status === 'OK' ? 'Trace within range' : `Excursion of ${r.excursion_minutes} min: stock quarantined, quality task opened` });
  const writeOff = useCommand(() => api.post('/expiry/write-off', { reason: window.prompt('Write-off reason', 'Monthly expiry sweep') || '' }), { success: 'Expired stock written off' });
  return (
    <Card title="Cold chain and expiry">
      <div className="mb-4 grid gap-4 md:grid-cols-2">
        {canSpec && (
          <form onSubmit={(e) => { e.preventDefault(); saveSpec.mutate(); }} className="grid gap-3 md:grid-cols-4 md:items-end">
            <Field label="Material">{(id) => <Input id={id} required value={spec.material} onChange={(e) => setSpec({ ...spec, material: e.target.value })} />}</Field>
            <Field label="Min °C">{(id) => <Input id={id} required type="number" step="0.5" value={spec.minC} onChange={(e) => setSpec({ ...spec, minC: e.target.value })} />}</Field>
            <Field label="Max °C">{(id) => <Input id={id} required type="number" step="0.5" value={spec.maxC} onChange={(e) => setSpec({ ...spec, maxC: e.target.value })} />}</Field>
            <Field label="Allowed minutes">{(id) => <Input id={id} type="number" min="0" value={spec.minutes} onChange={(e) => setSpec({ ...spec, minutes: e.target.value })} />}</Field>
            <Button type="submit" busy={saveSpec.isPending}>Save range</Button>
          </form>
        )}
        <form onSubmit={(e) => { e.preventDefault(); send.mutate(); }} className="grid gap-3 md:grid-cols-3 md:items-end">
          <Field label="On">{(id) => <Select id={id} value={reading.objectType} onChange={(e) => setReading({ ...reading, objectType: e.target.value })} options={[{ value: 'GOODS_RECEIPT', label: 'Goods receipt' }, { value: 'ASN', label: 'ASN' }]} />}</Field>
          <Field label="Document">{(id) => <Input id={id} required value={reading.ref} onChange={(e) => setReading({ ...reading, ref: e.target.value })} />}</Field>
          <Field label="Material">{(id) => <Input id={id} required value={reading.material} onChange={(e) => setReading({ ...reading, material: e.target.value })} />}</Field>
          <Field label="Logger">{(id) => <Input id={id} required value={reading.loggerId} onChange={(e) => setReading({ ...reading, loggerId: e.target.value })} />}</Field>
          <Field label="Readings (time,°C per line)">{(id) => <textarea id={id} required rows={3} className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm" placeholder="2026-11-04T06:00:00+05:30,5.1" value={reading.csv} onChange={(e) => setReading({ ...reading, csv: e.target.value })} />}</Field>
          <Button type="submit" variant="primary" busy={send.isPending}>Submit trace</Button>
        </form>
      </div>
      <DataTable<Reading>
        rows={readings.data ?? []} loading={readings.isLoading} error={readings.error} empty="No logger readings"
        columns={[{ key: 'object_ref', header: 'Document' }, { key: 'material', header: 'Material' }, { key: 'logger_id', header: 'Logger' },
          { key: 'min_seen_c', header: 'Range seen', render: (r) => `${r.min_seen_c} to ${r.max_seen_c} °C` },
          { key: 'excursion_minutes', header: 'Excursion', align: 'right', render: (r) => `${r.excursion_minutes} min` },
          { key: 'quarantined_qty', header: 'Quarantined', align: 'right', render: (r) => qty(r.quarantined_qty) },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> }]}
      />
      <p className="mt-2 text-xs text-slate-500">A quarantined lot is decided in the task inbox by a quality inspector (not the person who received it): release needs a documented justification, rejection writes the stock off.</p>
      <h3 className="mb-2 mt-6 text-sm font-semibold">Temperature ranges</h3>
      <DataTable<Spec> rows={specs.data ?? []} loading={specs.isLoading} error={specs.error} empty="No temperature ranges"
        columns={[{ key: 'material', header: 'Material', render: (s) => `${s.material} · ${s.description}` }, { key: 'label', header: 'Range', render: (s) => s.label ?? `${s.min_c}-${s.max_c} °C` },
          { key: 'max_excursion_minutes', header: 'Allowed excursion', align: 'right', render: (s) => s.max_excursion_minutes != null ? `${s.max_excursion_minutes} min` : 'rule default' }]} />
      <div className="mb-2 mt-6 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Expired stock on hand</h3>
        {scopes.includes('quality:decide') && <Button variant="danger" busy={writeOff.isPending} disabled={!expired.data?.length} onClick={() => writeOff.mutate()}>Write off expired stock</Button>}
      </div>
      <DataTable<Expired> rows={expired.data ?? []} loading={expired.isLoading} error={expired.error} empty="No expired stock"
        columns={[{ key: 'material', header: 'Material', render: (e) => `${e.material} · ${e.description}` }, { key: 'batch', header: 'Batch' },
          { key: 'plant', header: 'Location', render: (e) => `${e.plant} / ${e.storageLocation}` }, { key: 'qty', header: 'Quantity', align: 'right', render: (e) => qty(e.qty) },
          { key: 'expiry', header: 'Expired', render: (e) => date(e.expiry) }, { key: 'valueMinor', header: 'Value', align: 'right', render: (e) => inr(e.valueMinor) }]} />
    </Card>
  );
}

/** Par levels per storage location, replenishment on demand, and the value-analysis committee (VAC) report. */
export function ParLevelPanel({ canPlan }: { canPlan: boolean }) {
  const levels = useApi<Par[]>('/par-levels');
  const vac = useApi<Vac>('/par-levels/vac-report');
  const [form, setForm] = useState({ plant: '', storageLocation: '', material: '', parQty: '', triggerQty: '' });
  const save = useCommand(() => api.put('/par-levels', { plant: form.plant.trim(), storageLocation: form.storageLocation.trim(), material: form.material.trim(),
    parQty: Number(form.parQty), triggerQty: Number(form.triggerQty) }), { success: 'Par level saved' });
  const sweep = useCommand(() => api.post<{ requisitions: unknown[] }>('/par-levels/sweep', {}), { success: (r) => `${r.requisitions.length} replenishment requisition(s) raised` });
  return (
    <Card title="Par levels" actions={canPlan ? <Button variant="primary" busy={sweep.isPending} onClick={() => sweep.mutate()}>Replenish to par</Button> : undefined}>
      {canPlan && (
        <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="mb-4 grid gap-3 md:grid-cols-6 md:items-end">
          <Field label="Plant">{(id) => <Input id={id} required value={form.plant} onChange={(e) => setForm({ ...form, plant: e.target.value })} />}</Field>
          <Field label="Location">{(id) => <Input id={id} required value={form.storageLocation} onChange={(e) => setForm({ ...form, storageLocation: e.target.value })} />}</Field>
          <Field label="Material">{(id) => <Input id={id} required value={form.material} onChange={(e) => setForm({ ...form, material: e.target.value })} />}</Field>
          <Field label="Par">{(id) => <Input id={id} required type="number" min="1" step="any" value={form.parQty} onChange={(e) => setForm({ ...form, parQty: e.target.value })} />}</Field>
          <Field label="Replenish at">{(id) => <Input id={id} required type="number" min="0" step="any" value={form.triggerQty} onChange={(e) => setForm({ ...form, triggerQty: e.target.value })} />}</Field>
          <Button type="submit" busy={save.isPending}>Save</Button>
        </form>
      )}
      <DataTable<Par>
        rows={levels.data ?? []} loading={levels.isLoading} error={levels.error} empty="No par levels"
        columns={[{ key: 'plant', header: 'Location', render: (p) => `${p.plant} / ${p.storage_location}` }, { key: 'material', header: 'Material', render: (p) => `${p.material} · ${p.description}` },
          { key: 'par_qty', header: 'Par', align: 'right', render: (p) => qty(p.par_qty) }, { key: 'trigger_qty', header: 'Replenish at', align: 'right', render: (p) => qty(p.trigger_qty) },
          { key: 'onHand', header: 'On hand', align: 'right', render: (p) => qty(p.onHand) }, { key: 'onOrder', header: 'On order', align: 'right', render: (p) => qty(p.onOrder) },
          { key: 'belowTrigger', header: 'State', render: (p) => <StatusChip status={p.belowTrigger ? 'BELOW_TRIGGER' : 'OK'} /> }]}
      />
      <h3 className="mb-2 mt-6 text-sm font-semibold">Value-analysis committee report ({vac.data?.periodDays ?? 90} days)</h3>
      {vac.data && (
        <div className="mb-3 grid gap-3 md:grid-cols-3">
          <Kpi label="Value on hand" value={inr(vac.data.totals.valueOnHandMinor)} />
          <Kpi label="Expiring within 90 days" value={inr(vac.data.totals.expiringValueMinor)} tone={vac.data.totals.expiringValueMinor ? 'warn' : 'good'} />
          <Kpi label="Items below trigger" value={vac.data.totals.belowTrigger} tone={vac.data.totals.belowTrigger ? 'warn' : 'good'} />
        </div>
      )}
      <DataTable<Vac['items'][number]>
        rows={vac.data?.items ?? []} loading={vac.isLoading} error={vac.error} empty="No par-level items"
        columns={[{ key: 'material', header: 'Material' }, { key: 'usedQty', header: 'Used', align: 'right', render: (i) => qty(i.usedQty) },
          { key: 'daysOfSupply', header: 'Days of supply', align: 'right', render: (i) => i.daysOfSupply ?? '–' },
          { key: 'stockOutRisk', header: 'Stock-out risk', render: (i) => i.stockOutRisk ? <StatusChip status="AT_RISK" /> : 'No' },
          { key: 'expiringQty', header: 'Expiring', align: 'right', render: (i) => qty(i.expiringQty) },
          { key: 'parQty', header: 'Par → suggested', align: 'right', render: (i) => `${qty(i.parQty)} → ${i.suggestedPar ? qty(i.suggestedPar) : '–'}` },
          { key: 'parAdvice', header: 'Advice', render: (i) => label(i.parAdvice) }]}
      />
    </Card>
  );
}

/** Purchasing cards: holders and limits, statement import and reconciliation to purchase orders. */
export function PCardPanel({ scopes }: { scopes: string[] }) {
  const cards = useApi<PCard[]>('/pcards');
  const statements = useApi<Statement[]>('/pcard-statements');
  const admin = scopes.includes('payment:run') || scopes.includes('admin:rules');
  const [form, setForm] = useState({ holderName: '', holderEmail: '', issuer: '', cardLast4: '', perTxn: '', monthly: '', costObject: '' });
  const [stmt, setStmt] = useState({ issuer: '', period: '', json: '' });
  const issue = useCommand(() => api.post('/pcards', { holderName: form.holderName.trim(), holderEmail: form.holderEmail.trim() || null, issuer: form.issuer.trim(),
    cardLast4: form.cardLast4.trim(), perTxnLimitMinor: Math.round(Number(form.perTxn) * 100), monthlyLimitMinor: Math.round(Number(form.monthly) * 100),
    costObject: form.costObject.trim() || null }), { success: 'Card issued' });
  const importStatement = useCommand(() => api.post<{ number: string; exceptions: number }>('/pcard-statements', { issuer: stmt.issuer.trim(), period: stmt.period, lines: JSON.parse(stmt.json) }),
    { success: (s) => `${s.number} imported: ${s.exceptions} line(s) for review` });
  const setStatus = useCommand((a: { c: PCard; status: string }) => api.post(`/pcards/${a.c.number}/status`, { status: a.status, reason: window.prompt('Reason') || '' }, { ifMatch: `"${a.c.version}"` }),
    { success: 'Card updated' });
  return (
    <Card title="Purchasing cards">
      {admin && (
        <form onSubmit={(e) => { e.preventDefault(); issue.mutate(); }} className="mb-4 grid gap-3 md:grid-cols-4 md:items-end">
          <Field label="Holder">{(id) => <Input id={id} required value={form.holderName} onChange={(e) => setForm({ ...form, holderName: e.target.value })} />}</Field>
          <Field label="Holder e-mail">{(id) => <Input id={id} type="email" value={form.holderEmail} onChange={(e) => setForm({ ...form, holderEmail: e.target.value })} />}</Field>
          <Field label="Issuer">{(id) => <Input id={id} required value={form.issuer} onChange={(e) => setForm({ ...form, issuer: e.target.value })} />}</Field>
          <Field label="Last 4 digits">{(id) => <Input id={id} required pattern="\d{4}" maxLength={4} value={form.cardLast4} onChange={(e) => setForm({ ...form, cardLast4: e.target.value })} />}</Field>
          <Field label="Per transaction (₹)">{(id) => <Input id={id} required type="number" min="1" step="0.01" value={form.perTxn} onChange={(e) => setForm({ ...form, perTxn: e.target.value })} />}</Field>
          <Field label="Per month (₹)">{(id) => <Input id={id} required type="number" min="1" step="0.01" value={form.monthly} onChange={(e) => setForm({ ...form, monthly: e.target.value })} />}</Field>
          <Field label="Cost object" hint="COST_CENTER:6100">{(id) => <Input id={id} value={form.costObject} onChange={(e) => setForm({ ...form, costObject: e.target.value })} />}</Field>
          <Button type="submit" variant="primary" busy={issue.isPending}>Issue card</Button>
        </form>
      )}
      <DataTable<PCard>
        rows={cards.data ?? []} loading={cards.isLoading} error={cards.error} empty="No purchasing cards"
        columns={[{ key: 'number', header: 'Card', render: (c) => <span className="font-medium">{c.number}</span> }, { key: 'holder_name', header: 'Holder', render: (c) => `${c.holder_name} · ${c.issuer} ···${c.card_last4}` },
          { key: 'per_txn_limit_minor', header: 'Per transaction', align: 'right', render: (c) => inr(c.per_txn_limit_minor) },
          { key: 'monthly_limit_minor', header: 'Monthly', align: 'right', render: (c) => inr(c.monthly_limit_minor) },
          { key: 'monthToDateMinor', header: 'Month to date', align: 'right', render: (c) => `${inr(c.monthToDateMinor)} (${c.utilisationPct}%)` },
          { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
          { key: 'actions', header: 'Actions', render: (c) => admin && c.status !== 'CLOSED' ? (
            <div className="flex gap-1.5">
              {c.status === 'ACTIVE' ? <Button onClick={() => setStatus.mutate({ c, status: 'SUSPENDED' })}>Suspend</Button> : <Button onClick={() => setStatus.mutate({ c, status: 'ACTIVE' })}>Reactivate</Button>}
              <Button variant="danger" onClick={() => setStatus.mutate({ c, status: 'CLOSED' })}>Close</Button>
            </div>
          ) : '–' }]}
      />
      <h3 className="mb-2 mt-6 text-sm font-semibold">Statements</h3>
      {admin && (
        <form onSubmit={(e) => { e.preventDefault(); importStatement.mutate(); }} className="mb-3 grid gap-3 md:grid-cols-4 md:items-end">
          <Field label="Issuer">{(id) => <Input id={id} required value={stmt.issuer} onChange={(e) => setStmt({ ...stmt, issuer: e.target.value })} />}</Field>
          <Field label="Month">{(id) => <Input id={id} required type="month" value={stmt.period} onChange={(e) => setStmt({ ...stmt, period: e.target.value })} />}</Field>
          <Field label="Lines (JSON)" hint="cardLast4, txnRef, txnDate, merchant, mcc, amountMinor, po?">{(id) => <textarea id={id} required rows={3} className="w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-xs" value={stmt.json} onChange={(e) => setStmt({ ...stmt, json: e.target.value })} />}</Field>
          <Button type="submit" busy={importStatement.isPending}>Import and reconcile</Button>
        </form>
      )}
      <DataTable<Statement> rows={statements.data ?? []} loading={statements.isLoading} error={statements.error} empty="No statements imported"
        columns={[{ key: 'number', header: 'Statement' }, { key: 'issuer', header: 'Issuer' }, { key: 'period', header: 'Month' }, { key: 'line_count', header: 'Lines', align: 'right' },
          { key: 'total_minor', header: 'Total', align: 'right', render: (s) => inr(s.total_minor) }, { key: 'status', header: 'Status', render: (s) => <StatusChip status={s.status} /> }]} />
      <p className="mt-2 text-xs text-slate-500">Lines over a limit, on a blocked merchant category or above the PO threshold without a matching order go to the cost-object owner in the task inbox.</p>
    </Card>
  );
}
