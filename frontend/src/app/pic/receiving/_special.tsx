'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Kpi, LinkButton, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, date, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { isNumber, isPositive } from '../invoices/_components';
import { ConsignmentSettlementDialog } from '../invoices/_ops';

// ---------------------------------------------------------------- shared (P08 special stocks, BP §22 / §23)
type Reference = {
  plants: { code: string; name: string }[];
  costObjects: { type: string; code: string; name: string }[];
  materials: { number: string; description: string; uom: string }[];
};
/** Material master rows carry the lot-control attributes (batchManaged, expiryManaged, serialManaged). */
type MaterialRow = { id: string; number: string; description: string; base_uom: string; attributes: Record<string, unknown> | null };

/** Roles holding gr:post or req:create, the scopes POST /consignment/withdrawals accepts. */
export const WITHDRAW_ROLES = ['RECEIVER', 'REQUESTER', 'MRP_CONTROLLER', 'BUYER'];

// Serial numbers are entered comma- or line-separated, as at goods receipt.
const serialList = (text: string) => text.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
const COST_OBJECT = /^[A-Z_]+:[A-Za-z0-9-]+$/;

/** Material master by number (id and lot-control attributes); the API pages at 200, which covers the rehearsal tenants. */
export function useMaterials() {
  return useApi<{ items: MaterialRow[] }>('/materials?limit=200');
}

export function lotHref(material: string, batch: string) {
  return `/pic/receiving/lots/${encodeURIComponent(material)}/${encodeURIComponent(batch)}`;
}

// ---------------------------------------------------------------- consignment tab (receiving)
export function ConsignmentTab({ canWithdraw, canSettle }: { canWithdraw: boolean; canSettle: boolean }) {
  const [dialog, setDialog] = useState<'withdraw' | 'settle' | null>(null);
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Consignment stock (e.g. implants, fasteners, VMI) is supplier-owned while it sits in your storage location: the receipt creates no liability.
        A withdrawal does — consumption to a cost object (201K, e.g. a surgical case or production order) or transfer into own stock (411K) — at the
        consignment PO price. Accounts payable settles the withdrawals periodically by self-billing (ERS).
      </p>
      <div className="flex flex-wrap gap-2">
        {canWithdraw && <Button variant="primary" onClick={() => setDialog('withdraw')}>Withdraw from consignment</Button>}
        {canSettle && <Button onClick={() => setDialog('settle')}>Consignment settlement</Button>}
        <LinkButton href="/pic/invoices">Settlement documents in Invoices</LinkButton>
      </div>
      {!canWithdraw && <p className="text-xs text-slate-500">Withdrawals are posted by stores (receiver), requesters, MRP controllers and buyers.</p>}
      <p className="text-xs text-slate-500">
        Consignment receipts are posted from the Inbound tab like any goods receipt; consignment lines go to supplier-owned consignment stock. Use the Lot trace
        tab to see where a lot was received, what is left and which cases used it.
      </p>
      {dialog === 'withdraw' && <WithdrawalDialog onClose={() => setDialog(null)} />}
      {dialog === 'settle' && <ConsignmentSettlementDialog onClose={() => setDialog(null)} />}
    </div>
  );
}

type WithdrawalLot = { grLine: string; gr: string; po: string; poLine: number; batch: string; expiry: string | null; qty: string; serials: string[];
  liabilityMinor: number };
type Withdrawal = { material: string; plant: string; storageLocation: string; qty: string; purpose: string; movement: string; usageRef: string;
  costObject: string | null; liabilityMinor: number; lots: WithdrawalLot[];
  replenishment?: { requisition: string; status: string; qty: string; plant: string; storageLocation: string } };

export function WithdrawalDialog({ onClose }: { onClose: () => void }) {
  const reference = useApi<Reference>('/reference');
  const materials = useMaterials();
  const [material, setMaterial] = useState('');
  const [plant, setPlant] = useState('');
  const [sloc, setSloc] = useState('0001');
  const [purpose, setPurpose] = useState<'CONSUMPTION' | 'TRANSFER'>('CONSUMPTION');
  const [quantity, setQuantity] = useState('1');
  const [costObject, setCostObject] = useState('');
  const [usageRef, setUsageRef] = useState('');
  const [batch, setBatch] = useState('');
  const [serials, setSerials] = useState('');
  const [replenish, setReplenish] = useState(false);
  const [result, setResult] = useState<Withdrawal | null>(null);

  const master = materials.data?.items.find((m) => m.number === material.trim());
  const attrs = master?.attributes ?? {};
  // Unknown material (not in the first page of the master): offer the serial field and let the API decide.
  const serialManaged = master ? !!attrs.serialManaged : material.trim() !== '';
  const serialNos = serialList(serials);
  const plantCode = plant || reference.data?.plants[0]?.code || '';
  const problems = [
    !material.trim() && 'Choose the material',
    !plantCode && 'Choose the plant',
    !isPositive(quantity) && 'The quantity must be positive',
    usageRef.trim().length < 3 && 'Give the usage reference (surgical case, production order or pick list)',
    purpose === 'CONSUMPTION' && !COST_OBJECT.test(costObject.trim()) && 'A consumption is charged to a cost object, e.g. COST_CENTER:6100',
    purpose === 'TRANSFER' && costObject.trim() && !COST_OBJECT.test(costObject.trim()) && 'The cost object looks like COST_CENTER:6100',
    master && !!attrs.serialManaged && isNumber(quantity) && serialNos.length !== Number(quantity) && `${master.number} is serial-managed: give ${quantity} serial number(s) (${serialNos.length} entered)`,
    new Set(serialNos).size !== serialNos.length && 'Serial numbers must be unique',
  ].filter(Boolean) as string[];

  const withdraw = useCommand(() => api.post<Withdrawal>('/consignment/withdrawals', {
    material: material.trim(), plant: plantCode, qty: quantity, usage_ref: usageRef.trim(), purpose, storage_location: sloc.trim() || '0001',
    batch: batch.trim() || undefined, serials: serialNos, cost_object: costObject.trim() || undefined, replenish,
  }), {
    success: (r) => `${qty(r.qty)} ${r.material} withdrawn (${r.movement}) · liability ${inr(r.liabilityMinor)}${r.replenishment ? ` · ${r.replenishment.requisition} raised` : ''}`,
    onSuccess: setResult,
  });

  return (
    <Dialog open title="Withdraw from consignment stock" onClose={onClose}>
      {result ? <WithdrawalResult result={result} onClose={onClose} /> : (
        <>
          {reference.error && <ProblemBox error={reference.error} />}
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Material" hint={master ? `${master.description} · ${master.base_uom}${attrs.serialManaged ? ' · serial-managed' : ''}${attrs.batchManaged ? ' · lot-controlled' : ''}` : undefined}>
              {(id) => <>
                <Input id={id} list={`${id}-materials`} value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="Material number" />
                <datalist id={`${id}-materials`}>{(reference.data?.materials ?? []).map((m) => <option key={m.number} value={m.number}>{m.description}</option>)}</datalist>
              </>}
            </Field>
            <Field label="Plant">
              {(id) => <Select id={id} value={plantCode} onChange={(e) => setPlant(e.target.value)}
                options={(reference.data?.plants ?? []).map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />}
            </Field>
            <Field label="Storage location">{(id) => <Input id={id} maxLength={10} value={sloc} onChange={(e) => setSloc(e.target.value)} />}</Field>
            <Field label="Purpose">
              {(id) => <Select id={id} value={purpose} onChange={(e) => setPurpose(e.target.value as 'CONSUMPTION' | 'TRANSFER')} options={[
                { value: 'CONSUMPTION', label: 'Consumption to a cost object (201K)' }, { value: 'TRANSFER', label: 'Transfer to own stock (411K)' }]} />}
            </Field>
            <Field label="Quantity">{(id) => <Input id={id} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}</Field>
            <Field label={purpose === 'CONSUMPTION' ? 'Cost object (required)' : 'Cost object (optional)'} hint="TYPE:CODE, e.g. COST_CENTER:4100 or WBS:C-2207">
              {(id) => <>
                <Input id={id} list={`${id}-cost-objects`} value={costObject} onChange={(e) => setCostObject(e.target.value.toUpperCase())} />
                <datalist id={`${id}-cost-objects`}>{(reference.data?.costObjects ?? []).map((c) => <option key={`${c.type}:${c.code}`} value={`${c.type}:${c.code}`}>{c.name}</option>)}</datalist>
              </>}
            </Field>
            <Field label="Usage reference" hint="Surgical case, production order or pick list (3–60 characters)">
              {(id) => <Input id={id} maxLength={60} value={usageRef} onChange={(e) => setUsageRef(e.target.value)} />}
            </Field>
            <Field label="Lot / batch (optional)" hint="Empty: first-expiry-first-out across open lots">
              {(id) => <Input id={id} value={batch} onChange={(e) => setBatch(e.target.value)} />}
            </Field>
            {serialManaged && (
              <div className="md:col-span-2">
                <Field label={master ? 'Serial numbers used (one per unit)' : 'Serial numbers (required for serial-managed materials)'}
                  hint={serialNos.length ? `${serialNos.length} serial(s)` : 'Comma- or line-separated; the lots are taken from the serials'}>
                  {(id) => <Textarea id={id} value={serials} onChange={(e) => setSerials(e.target.value)} placeholder="SN-001, SN-002" className="font-mono text-xs" />}
                </Field>
              </div>
            )}
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4" checked={replenish} onChange={(e) => setReplenish(e.target.checked)} />
            Raise a replenishment requisition for the same quantity from the consignor
          </label>
          <p className="mt-3 text-xs text-slate-500">
            The withdrawal creates the liability to the supplier at the consignment PO price; self-billing settles it. Short consignment stock at the location is
            refused with the quantity available.
          </p>
          {problems.length > 0 && (material || usageRef) && <p className="mt-2 text-xs text-amber-700" role="status">{problems[0]}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={problems.length > 0} busy={withdraw.isPending} onClick={() => withdraw.mutate()}>Post withdrawal</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}

function WithdrawalResult({ result, onClose }: { result: Withdrawal; onClose: () => void }) {
  return (
    <div className="space-y-4">
      <p className="text-sm">
        <span className="font-semibold">{qty(result.qty)} {result.material}</span> withdrawn from {result.plant}/{result.storageLocation} · movement{' '}
        <span className="font-mono">{result.movement}</span> ({label(result.purpose)}) · {result.usageRef}{result.costObject ? ` → ${result.costObject}` : ''}
        {' '}· liability <span className="font-semibold">{inr(result.liabilityMinor)}</span>
      </p>
      <DataTable<WithdrawalLot & { id: string }> rows={result.lots.map((l) => ({ ...l, id: l.grLine }))} columns={[
        { key: 'batch', header: 'Lot', render: (l) => l.batch ? <Link className="font-medium text-[#1A56DB] hover:underline" href={lotHref(result.material, l.batch)}>{l.batch}</Link> : '–' },
        { key: 'expiry', header: 'Expiry', render: (l) => date(l.expiry) },
        { key: 'gr', header: 'Receipt', render: (l) => <Link className="text-[#1A56DB] hover:underline" href={`/pic/receiving/${encodeURIComponent(l.gr)}`}>{l.gr}</Link> },
        { key: 'po', header: 'Consignment PO', render: (l) => <Link className="text-[#1A56DB] hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(l.po)}`}>{l.po}/{l.poLine}</Link> },
        { key: 'qty', header: 'Quantity', align: 'right', render: (l) => qty(l.qty) },
        { key: 'serials', header: 'Serials', render: (l) => l.serials.length ? <span className="font-mono text-xs">{l.serials.join(', ')}</span> : '–' },
        { key: 'liabilityMinor', header: 'Liability', align: 'right', render: (l) => inr(l.liabilityMinor) },
      ]} />
      {result.replenishment && (
        <p className="text-sm">
          Replenishment <Link className="font-medium text-[#1A56DB] hover:underline" href={`/pic/requisitions/${encodeURIComponent(result.replenishment.requisition)}`}>{result.replenishment.requisition}</Link>
          {' '}for {qty(result.replenishment.qty)} to {result.replenishment.plant}/{result.replenishment.storageLocation} · <StatusChip status={result.replenishment.status} />
        </p>
      )}
      <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
    </div>
  );
}

// ---------------------------------------------------------------- lot trace search (receiving tab)
export function LotSearch() {
  const router = useRouter();
  const reference = useApi<Reference>('/reference');
  const [material, setMaterial] = useState('');
  const [batch, setBatch] = useState('');
  const ready = !!material.trim() && !!batch.trim();
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Recall traceability: every receipt of a lot with its receiving location, what is still on hand where, the cases or orders that used it (with serial
        numbers), return deliveries and every stock movement. The quality inspector can quarantine and return the lot from the trace.
      </p>
      <form className="grid items-end gap-3 md:grid-cols-[1fr_1fr_auto]" onSubmit={(e) => { e.preventDefault(); if (ready) router.push(lotHref(material.trim(), batch.trim())); }}>
        <Field label="Material">
          {(id) => <>
            <Input id={id} list={`${id}-materials`} value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="Material number" />
            <datalist id={`${id}-materials`}>{(reference.data?.materials ?? []).map((m) => <option key={m.number} value={m.number}>{m.description}</option>)}</datalist>
          </>}
        </Field>
        <Field label="Lot / batch">{(id) => <Input id={id} value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="e.g. LOT-2407-11" />}</Field>
        <Button type="submit" variant="primary" disabled={!ready}>Trace lot</Button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- lot trace view and recall
type Receipt = { gr: string; grLine: number; po: string; poLine: number; purchaseType: string; supplier: string | null; plant: string;
  storageLocation: string; postingDate: string; status: string; qty: string; expiry: string | null; serials: string[] };
type Usage = { usageRef: string | null; purpose: string | null; plant: string | null; storageLocation: string | null; qty: string | null; serials: string[];
  costObject: string | null; at: string };
type OnHand = { plant: string; storageLocation: string; stockType: string; qty: string };
type Return = { returnDelivery: string; qty: string; reason: string; status: string };
type Recalled = { grLine: string; gr: string; plant: string; storageLocation: string; stockType: string; qty: string; serials: string[]; returnDelivery: string;
  notice?: string };
type Movement = { movement: string; stockType: string; plant: string; storageLocation: string; qty: string; referenceType: string | null; reference: string | null; at: string };
export type LotTrace = { material: string; description: string; batch: string; suppliers: string[]; receipts: Receipt[]; receivedQty: string; usage: Usage[];
  usedQty: string; onHand: OnHand[]; returns: Return[]; recalls: Recalled[]; recalled: boolean; movements: Movement[] };
type RecallResult = { notice: string; material: string; batch: string; quarantined: Recalled[];
  replenishments: { requisition: string; status: string; qty: string; plant: string; storageLocation: string }[] };

// Recall quarantines what is on hand in these stock types (services/receiving.py recall_lot).
const RECALLABLE = ['UNRESTRICTED', 'CONSIGNMENT'];
const recallable = (trace: LotTrace) => trace.onHand.filter((s) => RECALLABLE.includes(s.stockType) && Number(s.qty) > 0);
const sum = (values: (string | null)[]) => values.reduce((s, v) => s + Number(v ?? 0), 0);
const grLink = (gr: string) => <Link className="font-medium text-[#1A56DB] hover:underline" href={`/pic/receiving/${encodeURIComponent(gr)}`}>{gr}</Link>;

export function LotTraceView({ trace, canRecall }: { trace: LotTrace; canRecall: boolean }) {
  const [open, setOpen] = useState(false);
  const toQuarantine = recallable(trace);
  const onHandQty = sum(trace.onHand.filter((s) => s.stockType !== 'SUBCONTRACTOR').map((s) => s.qty));
  return (
    <div className="space-y-5">
      {trace.recalled && (
        <div role="status" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          <p className="font-semibold">Lot recalled · notice {[...new Set(trace.recalls.map((r) => r.notice).filter(Boolean))].join(', ')}</p>
          <p className="mt-0.5">Units on hand were quarantined and returned to the supplier. Units already used are listed under Usage for clinical / customer follow-up.</p>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Received" value={qty(trace.receivedQty)} hint={`${trace.receipts.length} receipt line(s) · ${trace.suppliers.join(', ') || '–'}`} />
        <Kpi label="Used (withdrawn)" value={qty(trace.usedQty)} hint={`${trace.usage.length} case(s) / order(s)`} />
        <Kpi label="On hand" value={qty(onHandQty)} hint={`${toQuarantine.length} location(s) recallable`} tone={trace.recalled && onHandQty > 0 ? 'warn' : 'default'} />
        <Kpi label="Returned" value={qty(sum(trace.returns.map((r) => r.qty)))} hint={`${trace.returns.length} return deliver${trace.returns.length === 1 ? 'y' : 'ies'}`} />
      </div>
      {canRecall && (
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="danger" disabled={!toQuarantine.length} onClick={() => setOpen(true)}>Recall lot</Button>
          {!toQuarantine.length && <span className="text-xs text-slate-500">Nothing of this lot is on hand in unrestricted or consignment stock.</span>}
        </div>
      )}

      <Card title="Receipts">
        <DataTable<Receipt & { id: string }> rows={trace.receipts.map((r) => ({ ...r, id: `${r.gr}-${r.grLine}` }))} empty="No receipts" columns={[
          { key: 'gr', header: 'Goods receipt', render: (r) => <>{grLink(r.gr)} <span className="text-slate-500">/{r.grLine}</span></> },
          { key: 'po', header: 'PO', render: (r) => <Link className="text-[#1A56DB] hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(r.po)}`}>{r.po}/{r.poLine}</Link> },
          { key: 'purchaseType', header: 'Type', render: (r) => r.purchaseType.toLowerCase() },
          { key: 'supplier', header: 'Supplier', render: (r) => r.supplier ?? '–' },
          { key: 'location', header: 'Received at', render: (r) => `${r.plant}/${r.storageLocation}` },
          { key: 'postingDate', header: 'Posted', render: (r) => date(r.postingDate) },
          { key: 'expiry', header: 'Expiry', render: (r) => date(r.expiry) },
          { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty) },
          { key: 'serials', header: 'Serials', render: (r) => r.serials.length ? <span className="font-mono text-xs">{r.serials.join(', ')}</span> : '–' },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
        ]} />
      </Card>

      <Card title="Stock on hand by location">
        <DataTable<OnHand & { id: string }> rows={trace.onHand.map((s) => ({ ...s, id: `${s.plant}-${s.storageLocation}-${s.stockType}` }))}
          empty="Nothing of this lot is on hand" columns={[
            { key: 'plant', header: 'Plant' },
            { key: 'storageLocation', header: 'Storage location' },
            { key: 'stockType', header: 'Stock type', render: (s) => <StatusChip status={s.stockType} /> },
            { key: 'qty', header: 'Quantity', align: 'right', render: (s) => qty(s.qty) },
          ]} />
      </Card>

      <Card title="Usage · cases and orders">
        <DataTable<Usage & { id: string }> rows={trace.usage.map((u, i) => ({ ...u, id: `${u.at}-${i}` }))} empty="Not withdrawn or used yet" columns={[
          { key: 'usageRef', header: 'Case / order', render: (u) => <span className="font-medium">{u.usageRef ?? '–'}</span> },
          { key: 'purpose', header: 'Purpose', render: (u) => label(u.purpose) },
          { key: 'costObject', header: 'Cost object', render: (u) => u.costObject ?? '–' },
          { key: 'location', header: 'From', render: (u) => `${u.plant ?? '–'}/${u.storageLocation ?? '–'}` },
          { key: 'qty', header: 'Quantity', align: 'right', render: (u) => qty(u.qty) },
          { key: 'serials', header: 'Serials', render: (u) => u.serials.length ? <span className="font-mono text-xs">{u.serials.join(', ')}</span> : '–' },
          { key: 'at', header: 'When', render: (u) => dateTime(u.at) },
        ]} />
      </Card>

      {(trace.recalls.length > 0 || trace.returns.length > 0) && (
        <Card title="Recalls and return deliveries">
          <div className="space-y-4">
            {trace.recalls.length > 0 && <RecalledTable rows={trace.recalls} />}
            <DataTable<Return & { id: string }> rows={trace.returns.map((r) => ({ ...r, id: r.returnDelivery }))} empty="No return deliveries" columns={[
              { key: 'returnDelivery', header: 'Return delivery', render: (r) => <span className="font-mono">{r.returnDelivery}</span> },
              { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty) },
              { key: 'reason', header: 'Reason' },
              { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
            ]} />
          </div>
        </Card>
      )}

      <Card title={`Stock movements (${trace.movements.length})`}>
        <DataTable<Movement & { id: string }> rows={trace.movements.map((m, i) => ({ ...m, id: `${m.at}-${i}` }))} empty="No movements" columns={[
          { key: 'at', header: 'When', render: (m) => dateTime(m.at) },
          { key: 'movement', header: 'Mvt', render: (m) => <span className="font-mono text-xs">{m.movement}</span> },
          { key: 'stockType', header: 'Stock type', render: (m) => <StatusChip status={m.stockType} /> },
          { key: 'location', header: 'Location', render: (m) => `${m.plant}/${m.storageLocation}` },
          { key: 'qty', header: 'Quantity', align: 'right', render: (m) => <span className={Number(m.qty) < 0 ? 'text-red-700' : ''}>{qty(m.qty)}</span> },
          { key: 'reference', header: 'Reference', render: (m) => m.reference ? <>{m.reference} <span className="text-xs text-slate-500">{label(m.referenceType)}</span></> : '–' },
        ]} />
      </Card>

      {open && <RecallDialog trace={trace} onClose={() => setOpen(false)} />}
    </div>
  );
}

function RecalledTable({ rows }: { rows: Recalled[] }) {
  return (
    <DataTable<Recalled & { id: string }> rows={rows.map((r) => ({ ...r, id: `${r.grLine}-${r.returnDelivery}` }))} columns={[
      ...(rows.some((r) => r.notice) ? [{ key: 'notice', header: 'Notice', render: (r: Recalled) => r.notice ?? '–' }] : []),
      { key: 'gr', header: 'From receipt', render: (r) => grLink(r.gr) },
      { key: 'location', header: 'Location', render: (r) => `${r.plant}/${r.storageLocation}` },
      { key: 'stockType', header: 'Was', render: (r) => <StatusChip status={r.stockType} /> },
      { key: 'qty', header: 'Quarantined', align: 'right', render: (r) => qty(r.qty) },
      { key: 'serials', header: 'Serials', render: (r) => r.serials.length ? <span className="font-mono text-xs">{r.serials.join(', ')}</span> : '–' },
      { key: 'returnDelivery', header: 'Return delivery', render: (r) => <span className="font-mono">{r.returnDelivery}</span> },
    ]} />
  );
}

function RecallDialog({ trace, onClose }: { trace: LotTrace; onClose: () => void }) {
  const [notice, setNotice] = useState('');
  const [reason, setReason] = useState('');
  const [replenish, setReplenish] = useState(false);
  const [result, setResult] = useState<RecallResult | null>(null);
  const targets = recallable(trace);
  const consignment = targets.some((s) => s.stockType === 'CONSIGNMENT');
  const recall = useCommand(() => api.post<RecallResult>(`/lots/${encodeURIComponent(trace.material)}/${encodeURIComponent(trace.batch)}/recall`, {
    notice_ref: notice.trim(), reason: reason.trim(), replenish: consignment && replenish,
  }), {
    success: (r) => `Lot ${r.batch} recalled · ${qty(sum(r.quarantined.map((q) => q.qty)))} quarantined in ${r.quarantined.length} return deliver${r.quarantined.length === 1 ? 'y' : 'ies'}`,
    onSuccess: setResult,
  });
  return (
    <Dialog open title={`Recall ${trace.material} lot ${trace.batch}`} onClose={onClose}>
      {result ? (
        <div className="space-y-4">
          <p className="text-sm">Notice <span className="font-semibold">{result.notice}</span> · {result.quarantined.length} location(s) quarantined (344 / 344K) and returned to the supplier (122).</p>
          {result.quarantined.length ? <RecalledTable rows={result.quarantined} /> : <p className="text-sm text-slate-600">Nothing was on hand to quarantine.</p>}
          {result.replenishments.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Replacement requisitions</h3>
              <ul className="mt-1 divide-y divide-slate-100 text-sm">
                {result.replenishments.map((r) => (
                  <li key={r.requisition} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                    <Link className="font-medium text-[#1A56DB] hover:underline" href={`/pic/requisitions/${encodeURIComponent(r.requisition)}`}>{r.requisition}</Link>
                    <span>{qty(r.qty)} to {r.plant}/{r.storageLocation} <StatusChip status={r.status} /></span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-slate-500">Units already used ({qty(trace.usedQty)}) stay in the trace for follow-up with the cases or orders listed.</p>
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <>
          <p className="text-sm text-slate-700">Every unit of the lot still on hand is quarantined (344, 344K for consignment) and returned to the supplier (122) with a return delivery per receipt line:</p>
          <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
            {targets.map((s) => (
              <li key={`${s.plant}-${s.storageLocation}-${s.stockType}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5">
                <span>{s.plant}/{s.storageLocation} <StatusChip status={s.stockType} /></span>
                <span className="font-semibold tabular-nums">{qty(s.qty)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-3 grid gap-3">
            <Field label="Supplier notice reference" hint="Field safety notice / recall letter number (3–60 characters)">
              {(id) => <Input id={id} maxLength={60} value={notice} onChange={(e) => setNotice(e.target.value)} />}
            </Field>
            <Field label="Reason">{(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          </div>
          {consignment && (
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4" checked={replenish} onChange={(e) => setReplenish(e.target.checked)} />
              Re-order the recalled consignment quantity from the consignor
            </label>
          )}
          <p className="mt-3 text-xs text-slate-500">
            Own stock comes back by credit note (the quantity counts as rejected on the PO line); consignment stock was never a liability. Used units ({qty(trace.usedQty)})
            are not moved.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="danger" disabled={notice.trim().length < 3 || reason.trim().length < 3 || !targets.length} busy={recall.isPending}
              onClick={() => recall.mutate()}>Quarantine and return</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}
