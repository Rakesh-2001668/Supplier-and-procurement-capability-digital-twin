'use client';

import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { Button, Card, Field, Input, LinkButton, PageHeader, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { api, Paged } from '@/lib/pic/api';
import { label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// PO-01 order creation besides the requisition path (flow fixes B2): a release order against a live contract, a manual order with
// reason and purpose code, or an order from a planned order through its MRP requisition (the MRP controller's step).
type Mode = 'CONTRACT' | 'MANUAL' | 'PLANNED_ORDER';
type ListedContract = { number: string; type: string; status: string; supplier_code: string; title: string; currency: string | null };
type ContractLine = { line_no: number; description: string; plant: string; uom: string; target_qty: string; released_qty: string };
type ContractDetail = { number: string; currency: string | null; lines: ContractLine[] };
type Supplier = { code: string; legal_name: string; status: string };
type Org = { plants: { code: string; name: string }[] };
type Created = { id?: string; requisition?: string; requisitionStatus?: string; next?: string; purchaseOrders?: { id: string }[] };
type ManualLine = { material: string; description: string; materialGroup: string; qty: string; uom: string; price: string; needDate: string;
  costCentre: string };

const MODES: { id: Mode; title: string; text: string }[] = [
  { id: 'CONTRACT', title: 'Release order against a contract', text: 'Supplier, price, terms and tolerances come from the contract; the quantity must fit what the contract line still has.' },
  { id: 'MANUAL', title: 'Manual order', text: 'No requisition behind it: state why and the purpose code. Priced by you, price-checked, always approved by the PO bands.' },
  { id: 'PLANNED_ORDER', title: 'From a planned order', text: 'Converts the planned order to its MRP requisition (DMN-01 approval) and orders it at once when it is approved without a human step.' },
];

const emptyLine = (): ManualLine => ({ material: '', description: '', materialGroup: '', qty: '', uom: 'EA', price: '', needDate: '', costCentre: '' });
const positive = (v: string) => v.trim() !== '' && !Number.isNaN(Number(v)) && Number(v) > 0;

export default function NewPurchaseOrder() {
  const router = useRouter();
  const [idempotencyKey] = useState(() => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`));
  const [mode, setMode] = useState<Mode>('CONTRACT');
  const [contractRef, setContractRef] = useState('');
  const [releaseQty, setReleaseQty] = useState<Record<number, string>>({});
  const [needDate, setNeedDate] = useState('');
  const [currency, setCurrency] = useState('');
  const [purchasingOrg, setPurchasingOrg] = useState('');
  const [purposeCode, setPurposeCode] = useState('');
  const [reason, setReason] = useState('');
  const [supplierCode, setSupplierCode] = useState('');
  const [plant, setPlant] = useState('');
  const [plannedOrder, setPlannedOrder] = useState('');
  const [lines, setLines] = useState<ManualLine[]>([emptyLine()]);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [pending, setPending] = useState<Created | null>(null);

  const contracts = useApi<Paged<ListedContract>>(mode === 'CONTRACT' ? '/contracts?limit=200' : null);
  const live = (contracts.data?.items ?? []).filter((c) => ['ACTIVE', 'EXPIRING'].includes(c.status) && !['MASTER_AGREEMENT', 'NDA'].includes(c.type));
  const detail = useApi<ContractDetail>(mode === 'CONTRACT' && contractRef ? `/contracts/${encodeURIComponent(contractRef)}` : null);
  const suppliers = useApi<Paged<Supplier>>(mode === 'MANUAL' ? '/suppliers?limit=200' : null);
  const org = useApi<Org>('/admin/organisation');
  const plants = org.data?.plants ?? [];

  const create = useCommand((body: Record<string, unknown>) => api.post<Created>('/purchase-orders', body, { idempotencyKey }), {
    success: (r) => (r.id ? `Purchase order ${r.id} created` : r.purchaseOrders?.length ? `${r.purchaseOrders.length} purchase orders created`
      : `Requisition ${r.requisition ?? ''} created`),
    onSuccess: (r) => {
      const first = r.id ?? r.purchaseOrders?.[0]?.id;
      if (first) router.push(`/pic/purchase-orders/${encodeURIComponent(first)}`);
      else setPending(r);
    },
  });

  const updateLine = (i: number, patch: Partial<ManualLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const header = { currency: currency.trim() ? currency.trim().toUpperCase() : undefined, purchasingOrg: purchasingOrg.trim() || undefined };

  function submit(e: FormEvent) {
    e.preventDefault();
    if (currency.trim() && !/^[A-Za-z]{3}$/.test(currency.trim())) { setInvalid('Currency is a three-letter ISO code, e.g. USD.'); return; }
    if (mode === 'CONTRACT') {
      const chosen = (detail.data?.lines ?? []).filter((l) => positive(releaseQty[l.line_no] ?? ''));
      if (!contractRef || !chosen.length) { setInvalid('Choose a contract and a positive quantity on at least one line.'); return; }
      setInvalid(null);
      create.mutate({ source: { type: 'CONTRACT', id: contractRef }, purposeCode: purposeCode.trim() || undefined, ...header,
        contractLines: chosen.map((l) => ({ line: l.line_no, qty: releaseQty[l.line_no].trim(), needDate: needDate || undefined })) });
      return;
    }
    if (mode === 'PLANNED_ORDER') {
      if (!plannedOrder.trim()) { setInvalid('Give the planned order number, e.g. PLO-55822.'); return; }
      setInvalid(null);
      create.mutate({ source: { type: 'PLANNED_ORDER', id: plannedOrder.trim().toUpperCase() }, purposeCode: purposeCode.trim() || undefined, ...header });
      return;
    }
    if (!supplierCode.trim() || !(plant || plants[0]?.code)) { setInvalid('Supplier and plant are required.'); return; }
    if (reason.trim().length < 10) { setInvalid('Give the reason this order is raised without a requisition (at least 10 characters).'); return; }
    if (!purposeCode.trim()) { setInvalid('A purpose code is mandatory on every order (P01).'); return; }
    const bad = lines.findIndex((l) => !positive(l.qty) || !positive(l.price) || (!l.material.trim() && (!l.description.trim() || !l.materialGroup.trim() || !l.costCentre.trim())));
    if (bad >= 0) { setInvalid(`Line ${(bad + 1) * 10}: quantity and unit price above zero; a free-text line also needs description, material group and cost centre.`); return; }
    setInvalid(null);
    create.mutate({
      source: { type: 'MANUAL' }, supplierId: supplierCode.trim().toUpperCase(), plant: plant || plants[0]?.code, purposeCode: purposeCode.trim(),
      reason: reason.trim(), ...header,
      manualLines: lines.map((l) => ({
        material: l.material.trim() || undefined, description: l.description.trim() || undefined, materialGroup: l.materialGroup.trim() || undefined,
        qty: l.qty.trim(), uom: l.uom.trim().toUpperCase() || undefined, unitPriceMinor: rupeesToMinor(l.price), needDate: l.needDate || undefined,
        accountAssignmentType: l.costCentre.trim() ? 'COST_CENTER' : undefined, accountAssignmentCode: l.costCentre.trim() || undefined,
      })),
    });
  }

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PO-01 · New order" title="New purchase order"
        subtitle="Orders from approved requisitions are created in the buyer workbench. Here: a release order against a contract, a manual order, or an order from a planned order."
        actions={<LinkButton href="/pic/purchase-orders">Back to purchase orders</LinkButton>} />

      <form onSubmit={submit} className="space-y-5">
        <Card title="How is the order created?">
          <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Order source">
            {MODES.map((m) => (
              <button key={m.id} type="button" role="radio" aria-checked={mode === m.id} onClick={() => { setMode(m.id); setInvalid(null); setPending(null); }}
                className={`rounded-lg border px-3 py-2 text-left text-sm ${mode === m.id ? 'border-[#1A56DB] bg-blue-50 ring-1 ring-[#1A56DB]' : 'border-slate-200 hover:bg-slate-50'}`}>
                <span className="font-semibold">{m.title}</span>
                <span className="mt-0.5 block text-xs text-slate-600">{m.text}</span>
              </button>
            ))}
          </div>
        </Card>

        {mode === 'CONTRACT' && (
          <Card title="Contract and lines">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Contract (required)" hint={contracts.isLoading ? 'Loading contracts…' : `${live.length} live call-off contracts`}>
                {(id) => <Select id={id} value={contractRef} onChange={(e) => { setContractRef(e.target.value); setReleaseQty({}); }}
                  options={[{ value: '', label: 'Choose a contract' }, ...live.map((c) => ({ value: c.number, label: `${c.number} · ${c.supplier_code} · ${c.title}` }))]} />}
              </Field>
              <Field label="Need date" hint="Default: in 14 days; must lie in the contract validity">{(id) => <Input id={id} type="date" value={needDate} onChange={(e) => setNeedDate(e.target.value)} />}</Field>
            </div>
            {detail.error && <ProblemBox error={detail.error} />}
            {detail.data && (
              <table className="mt-3 w-full text-sm">
                <caption className="sr-only">Contract lines</caption>
                <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Line</th><th>Description</th><th>Plant</th><th className="text-right">Released / target</th><th className="text-right">Release qty</th></tr></thead>
                <tbody>
                  {detail.data.lines.map((l) => (
                    <tr key={l.line_no} className="border-t border-slate-100">
                      <td className="py-1">{l.line_no}</td><td>{l.description}</td><td>{l.plant}</td>
                      <td className="text-right">{Number(l.released_qty).toLocaleString('en-IN')} / {Number(l.target_qty).toLocaleString('en-IN')} {l.uom}</td>
                      <td className="text-right">
                        <Input aria-label={`Release quantity for line ${l.line_no}`} inputMode="decimal" className="w-28 text-right"
                          value={releaseQty[l.line_no] ?? ''} onChange={(e) => setReleaseQty((q) => ({ ...q, [l.line_no]: e.target.value }))} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}

        {mode === 'MANUAL' && (
          <Card title="Supplier, reason and lines">
            <datalist id="po-supplier-codes">{suppliers.data?.items.map((s) => <option key={s.code} value={s.code}>{s.legal_name}</option>)}</datalist>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Supplier code (required)">{(id) => <Input id={id} list="po-supplier-codes" value={supplierCode} onChange={(e) => setSupplierCode(e.target.value)} placeholder="e.g. KD002" />}</Field>
              <Field label="Plant (required)">
                {(id) => <Select id={id} value={plant || plants[0]?.code || ''} onChange={(e) => setPlant(e.target.value)} options={plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />}
              </Field>
            </div>
            <div className="mt-3">
              <Field label="Reason for ordering without a requisition (required)" hint="Kept on the order and in the audit trail, shown to the approvers">
                {(id) => <Textarea id={id} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Breakdown of press 4: spare needed before a requisition can be approved" />}
              </Field>
            </div>
            <div className="mt-3 space-y-3">
              {lines.map((l, i) => (
                <fieldset key={i} className="grid gap-2 rounded-lg border border-slate-200 p-3 sm:grid-cols-4">
                  <legend className="px-1 text-xs font-semibold text-slate-600">Line {(i + 1) * 10}</legend>
                  <Field label="Material">{(id) => <Input id={id} value={l.material} onChange={(e) => updateLine(i, { material: e.target.value })} placeholder="number, or leave empty for free text" />}</Field>
                  <Field label="Description">{(id) => <Input id={id} value={l.description} onChange={(e) => updateLine(i, { description: e.target.value })} />}</Field>
                  <Field label="Material group">{(id) => <Input id={id} value={l.materialGroup} onChange={(e) => updateLine(i, { materialGroup: e.target.value })} />}</Field>
                  <Field label="Cost centre" hint="Free text and non-stock lines">{(id) => <Input id={id} value={l.costCentre} onChange={(e) => updateLine(i, { costCentre: e.target.value })} />}</Field>
                  <Field label="Quantity">{(id) => <Input id={id} inputMode="decimal" value={l.qty} onChange={(e) => updateLine(i, { qty: e.target.value })} />}</Field>
                  <Field label="Unit">{(id) => <Input id={id} value={l.uom} onChange={(e) => updateLine(i, { uom: e.target.value })} />}</Field>
                  <Field label={`Unit price (${currency.trim().toUpperCase() || 'company currency'})`}>{(id) => <Input id={id} inputMode="decimal" value={l.price} onChange={(e) => updateLine(i, { price: e.target.value })} />}</Field>
                  <Field label="Need date">{(id) => <Input id={id} type="date" value={l.needDate} onChange={(e) => updateLine(i, { needDate: e.target.value })} />}</Field>
                  {lines.length > 1 && <div className="sm:col-span-4"><Button type="button" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>Remove line</Button></div>}
                </fieldset>
              ))}
              <Button type="button" onClick={() => setLines((ls) => [...ls, emptyLine()])}>Add line</Button>
            </div>
          </Card>
        )}

        {mode === 'PLANNED_ORDER' && (
          <Card title="Planned order">
            <Field label="Planned order (required)" hint="Converting is the MRP controller's step; the requisition follows the DMN-01 approval like any other">
              {(id) => <Input id={id} value={plannedOrder} onChange={(e) => setPlannedOrder(e.target.value)} placeholder="e.g. PLO-55822" />}
            </Field>
            {pending?.requisition && (
              <p role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
                Requisition <a className="underline" href={`/pic/requisitions/${encodeURIComponent(pending.requisition)}`}>{pending.requisition}</a> is {label(pending.requisitionStatus ?? '')}: {pending.next}
              </p>
            )}
          </Card>
        )}

        <Card title="Order header">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label={mode === 'MANUAL' ? 'Purpose code (required)' : 'Purpose code'} hint={mode === 'CONTRACT' ? 'Default CONTRACT_RELEASE' : mode === 'PLANNED_ORDER' ? 'Default MRP_REPLENISHMENT' : 'P01: every order carries its purpose'}>
              {(id) => <Input id={id} value={purposeCode} onChange={(e) => setPurposeCode(e.target.value)} placeholder="e.g. MAINTENANCE" />}
            </Field>
            <Field label="Currency" hint="Default: the contract's, else the company code's. A foreign currency needs an exchange rate for today.">
              {(id) => <Input id={id} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} placeholder="e.g. USD" />}
            </Field>
            <Field label="Purchasing organisation" hint="Default: the purchasing group of the plant, else the company code's organisation">
              {(id) => <Input id={id} value={purchasingOrg} onChange={(e) => setPurchasingOrg(e.target.value)} />}
            </Field>
          </div>
        </Card>

        {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">{invalid}</p>}
        {create.error && <ProblemBox error={create.error} />}
        <Button type="submit" variant="primary" busy={create.isPending}>Create order</Button>
      </form>
    </div>
  );
}
