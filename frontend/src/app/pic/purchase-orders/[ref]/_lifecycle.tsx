'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- shared types
export type LifecyclePo = { number: string; status: string; version: number; row_version?: number;
  lines: { line_no: number; description: string; qty: string; uom: string; plant?: string; purchase_type: string; shipped_qty: string;
    received_qty: string; accepted_qty: string; invoiced_qty: string; ses_required: boolean; ses_approved_minor?: number; invoiced_minor?: number;
    unit_price_minor?: number; need_date?: string }[] };

// PO state machine (services/order.py SM): cancel from DRAFT / IN_APPROVAL / RELEASED / TRANSMITTED / CONFIRMED (nothing shipped,
// received or invoiced), close from RECEIVED / INVOICED, short-close from PARTIALLY_RECEIVED, re-submit from DRAFT (approval returned).
export const CANCELLABLE = ['DRAFT', 'IN_APPROVAL', 'RELEASED', 'TRANSMITTED', 'CONFIRMED'];
export const CLOSABLE = ['RECEIVED', 'INVOICED'];
export const SHORT_CLOSABLE = ['PARTIALLY_RECEIVED'];
export const RESUBMITTABLE = ['DRAFT'];
/** ETag of the PO read model (row version) for If-Match on PO writes. */
export const ifMatch = (po: { row_version?: number }) => (po.row_version !== undefined ? `"${po.row_version}"` : undefined);
// Components can be provided while the order is open for receipt (services/receiving.py provide_components).
const PROVIDABLE = ['RELEASED', 'TRANSMITTED', 'CONFIRMED', 'PARTIALLY_RECEIVED'];

/** Lines that block a cancellation (rule PO-CANCEL): anything shipped, received, invoiced or service-approved. */
export function cancelBlockers(po: LifecyclePo): number[] {
  return po.lines.filter((l) => Number(l.shipped_qty) > 0 || Number(l.received_qty) > 0 || Number(l.invoiced_qty) > 0 || Number(l.ses_approved_minor ?? 0) > 0)
    .map((l) => l.line_no);
}

/** Lines that block closing (rule PO-CLOSE): accepted but not invoiced, or approved service value not invoiced. */
export function closeBlockers(po: LifecyclePo): number[] {
  return po.lines.filter((l) => Number(l.accepted_qty) > Number(l.invoiced_qty)
    || (l.ses_required && Number(l.ses_approved_minor ?? 0) > Number(l.invoiced_minor ?? 0))).map((l) => l.line_no);
}

// ---------------------------------------------------------------- cancel (PO-CANCEL)
export function CancelPoDialog({ po, onClose }: { po: LifecyclePo; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const blockers = cancelBlockers(po);
  const cancel = useCommand(() => api.post<{ po: string; status: string; from: string }>(`/purchase-orders/${encodeURIComponent(po.number)}/cancel`,
    { reason: reason.trim() }), {
    success: (r) => `${r.po} cancelled (was ${r.from.replace(/_/g, ' ').toLowerCase()}); the requisition quantity is released for re-ordering`,
    onSuccess: onClose,
  });
  const short = reason.trim().length < 3;
  return (
    <Dialog open title={`Cancel ${po.number} v${po.version}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        Open approval and confirmation tasks close, the requisition quantity is released for re-ordering, contract consumption booked at release is
        reversed, and the supplier portal and the ERP are informed. A cancellation cannot be undone. Service entries still in approval block it.
      </p>
      {blockers.length > 0 && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
          Line(s) {blockers.join(', ')} already have shipments, receipts or invoices: this order cannot be cancelled. Change the order or close it once settled.
        </p>
      )}
      <div className="mt-3">
        <Field label="Reason (sent to the supplier and audited)" hint="At least 3 characters, e.g. supplier rejected the order, demand withdrawn">
          {(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Keep order</Button>
        <Button variant="danger" disabled={short || blockers.length > 0} busy={cancel.isPending} onClick={() => cancel.mutate()}>Cancel order</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- close (PO-CLOSE)
export function ClosePoDialog({ po, onClose }: { po: LifecyclePo; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const blockers = closeBlockers(po);
  const close = useCommand(() => api.post<{ po: string; status: string; closedRequisitions: string[] }>(`/purchase-orders/${encodeURIComponent(po.number)}/close`,
    { reason: reason.trim() }), {
    success: (r) => `${r.po} closed${r.closedRequisitions.length ? ` · requisition ${r.closedRequisitions.join(', ')} closed with it` : ''}`,
    onSuccess: onClose,
  });
  const short = reason.trim().length < 3;
  return (
    <Dialog open title={`Close ${po.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        Closing ends the order: nothing more can be received or invoiced against it. It is allowed when every accepted quantity is invoiced and no invoice
        on the order is still in process. A requisition whose orders are all closed or cancelled is closed with it.
      </p>
      {blockers.length > 0 && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
          Line(s) {blockers.join(', ')} still have received value to invoice. Capture and post the invoice first.
        </p>
      )}
      <div className="mt-3">
        <Field label="Reason (audited)" hint="e.g. fully delivered and invoiced, rejected lot returned in full">
          {(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
      <p className="mt-2 text-xs text-slate-500">An invoice still in matching or approval blocks closing; the API names it if so.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={short || blockers.length > 0} busy={close.isPending} onClick={() => close.mutate()}>Close order</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- short-close (PO-CLOSE) a partly received order
export function ShortClosePoDialog({ po, onClose }: { po: LifecyclePo; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const blockers = closeBlockers(po);
  const open = po.lines.filter((l) => Number(l.qty) > Number(l.received_qty));
  const shortClose = useCommand(() => api.post<{ po: string; status: string; released: { line: number; releasedQty: string }[] }>(
    `/purchase-orders/${encodeURIComponent(po.number)}/short-close`, { reason: reason.trim() }), {
    success: (r) => `${r.po} short-closed · ${r.released.map((x) => `line ${x.line}: ${qty(x.releasedQty)} released`).join(', ') || 'nothing open'}`,
    onSuccess: onClose,
  });
  const short = reason.trim().length < 3;
  return (
    <Dialog open title={`Short-close ${po.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        The rest of the order will not be delivered: the order closes once everything received is invoiced, and the open quantity goes back to the
        requisition for re-ordering. Open confirmation and approval tasks close. An ASN still in transit, a lot in inspection or an invoice or service
        entry in process blocks the short-close; the API names it.
      </p>
      {open.length > 0 && (
        <ul className="mt-3 text-sm text-slate-700">
          {open.map((l) => <li key={l.line_no}>Line {l.line_no} · {l.description}: {qty(Number(l.qty) - Number(l.received_qty), l.uom)} released</li>)}
        </ul>
      )}
      {blockers.length > 0 && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
          Line(s) {blockers.join(', ')} still have received value to invoice. Capture and post the invoice first.
        </p>
      )}
      <div className="mt-3">
        <Field label="Reason (audited)" hint="e.g. supplier cannot deliver the balance; requirement re-sourced">
          {(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={short || blockers.length > 0} busy={shortClose.isPending} onClick={() => shortClose.mutate()}>Short-close order</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- re-submit an order returned by its approver (DRAFT)
export function ResubmitPoDialog({ po, onClose }: { po: LifecyclePo; onClose: () => void }) {
  const [drafts, setDrafts] = useState(() => po.lines.map((l) => ({ line: l.line_no, qty: String(Number(l.qty)),
    price: l.unit_price_minor !== undefined ? String(l.unit_price_minor / 100) : '', needDate: l.need_date ?? '' })));
  const [reason, setReason] = useState('');
  const [deviationReason, setDeviationReason] = useState('');
  const changes = drafts.flatMap((d) => {
    const line = po.lines.find((l) => l.line_no === d.line);
    if (!line) return [];
    const change: Record<string, string | number> = { line: d.line };
    if (Number(d.qty) !== Number(line.qty)) change.qty = d.qty.trim();
    if (d.price && line.unit_price_minor !== undefined && Math.round(Number(d.price) * 100) !== line.unit_price_minor) change.unit_price = d.price.trim();
    if (d.needDate && d.needDate !== line.need_date) change.need_date = d.needDate;
    return Object.keys(change).length > 1 ? [change] : [];
  });
  const invalid = drafts.some((d) => !(Number(d.qty) > 0) || (d.price !== '' && !(Number(d.price) > 0)));
  const resubmit = useCommand(() => api.post<{ po: string; status: string }>(`/purchase-orders/${encodeURIComponent(po.number)}/resubmit`,
    { reason: reason.trim(), changes, deviationReason: deviationReason.trim() || undefined }, { ifMatch: ifMatch(po) }), {
    success: (r) => `${r.po} re-submitted · ${r.status.replace(/_/g, ' ').toLowerCase()}`, onSuccess: onClose,
  });
  const update = (i: number, patch: Partial<(typeof drafts)[number]>) => setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  return (
    <Dialog open title={`Correct and re-submit ${po.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        The approver returned this order. Correct quantity (within the requisition), price or need date; the order is validated and routed for approval
        again. A price outside the contract tolerance needs a deviation reason.
      </p>
      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-2 py-2">Line</th><th className="px-2 py-2">Quantity</th><th className="px-2 py-2">Unit price (₹)</th><th className="px-2 py-2">Need date</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {drafts.map((d, i) => (
              <tr key={d.line}>
                <td className="px-2 py-2">{d.line} · {po.lines[i]?.description}</td>
                <td className="px-2 py-2"><Input aria-label={`Quantity of line ${d.line}`} inputMode="decimal" className="w-28" value={d.qty} onChange={(e) => update(i, { qty: e.target.value })} /></td>
                <td className="px-2 py-2"><Input aria-label={`Unit price of line ${d.line}`} inputMode="decimal" className="w-28" value={d.price} onChange={(e) => update(i, { price: e.target.value })} /></td>
                <td className="px-2 py-2"><Input aria-label={`Need date of line ${d.line}`} type="date" value={d.needDate} onChange={(e) => update(i, { needDate: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 grid gap-3">
        <Field label="What was corrected (for the approver)">{(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        {changes.some((c) => 'unit_price' in c) && (
          <Field label="Deviation reason (if the price is outside the contract tolerance)">
            {(id) => <Textarea id={id} maxLength={500} value={deviationReason} onChange={(e) => setDeviationReason(e.target.value)} />}
          </Field>
        )}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={reason.trim().length < 3 || invalid} busy={resubmit.isPending} onClick={() => resubmit.mutate()}>Re-submit for approval</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- subcontracting components (P08, movements 541 / 543)
type Component = { material: string; materialId: string; description: string; qtyPer: string; qty: string; uom: string };
type Components = { po: string; lines: { line: number; components: Component[] }[];
  atSubcontractor: { material: string | null; plant: string; batch: string; qty: string }[] };
type AuditEvent = { seq: number; action: string; after: { line?: number; components?: { material: string; qty: string; batch: string; from: string }[] } | null };
type ComponentRow = Component & { id: string; line: number; provided: number; consumed: number; atSupplier: number; outstanding: number };

/** Components the buyer provides to the subcontractor for each subcontracting line: planned, provided (541), consumed on receipt (543), at the supplier. */
export function SubcontractingTab({ po, canProvide }: { po: LifecyclePo; canProvide: boolean }) {
  const path = `/purchase-orders/${encodeURIComponent(po.number)}`;
  const { data, isLoading, error } = useApi<Components>(`${path}/components`);
  // The component read model has no per-order provided quantity; it is the sum of this order's COMPONENTS_PROVIDED audit events.
  const audit = useApi<AuditEvent[]>(`/audit/PURCHASE_ORDER/${encodeURIComponent(po.number)}`);
  const [providing, setProviding] = useState<number | null>(null);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.lines.length) return <Empty title="No subcontracting lines" />;

  const provided = new Map<string, number>();
  for (const e of audit.data ?? []) {
    if (e.action !== 'COMPONENTS_PROVIDED' || !e.after?.components) continue;
    for (const c of e.after.components) provided.set(`${e.after.line}|${c.material}`, (provided.get(`${e.after.line}|${c.material}`) ?? 0) + Number(c.qty));
  }
  const atSupplier = (material: string, plant?: string) => data.atSubcontractor
    .filter((s) => s.material === material && (!plant || s.plant === plant)).reduce((sum, s) => sum + Number(s.qty), 0);
  const rows: ComponentRow[] = data.lines.flatMap(({ line, components }) => {
    const poLine = po.lines.find((l) => l.line_no === line);
    return components.map((c) => {
      const given = provided.get(`${line}|${c.material}`) ?? 0;
      const consumed = Number(c.qtyPer) * Number(poLine?.received_qty ?? 0);
      return { ...c, id: `${line}-${c.material}`, line, provided: given, consumed, atSupplier: atSupplier(c.material, poLine?.plant),
        outstanding: Math.max(Number(c.qty) - given, 0) };
    });
  });
  const open = canProvide && PROVIDABLE.includes(po.status);

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        The buyer&apos;s own components are transferred to stock at the subcontractor (movement 541) before the finished part is made. Receiving the finished
        part consumes them first-provided-first-consumed (543); a receipt is refused while too few components are at the supplier.
      </p>
      {audit.error && <ProblemBox error={audit.error} />}
      <DataTable<ComponentRow> rows={rows} columns={[
        { key: 'line', header: 'Line' },
        { key: 'material', header: 'Component', render: (c) => <><span className="font-medium">{c.material}</span> <span className="text-slate-500">{c.description}</span></> },
        { key: 'qtyPer', header: 'Per part', align: 'right', render: (c) => qty(c.qtyPer) },
        { key: 'qty', header: 'Planned', align: 'right', render: (c) => qty(c.qty, c.uom) },
        { key: 'provided', header: 'Provided (541)', align: 'right', render: (c) => audit.isLoading ? '…' : qty(c.provided) },
        { key: 'consumed', header: 'Consumed (543)', align: 'right', render: (c) => qty(c.consumed) },
        { key: 'atSupplier', header: 'At subcontractor', align: 'right', render: (c) => qty(c.atSupplier) },
        { key: 'outstanding', header: 'Still to provide', align: 'right', render: (c) => c.outstanding > 0
          ? <span className="font-semibold text-amber-700">{qty(c.outstanding)}</span> : '0' },
      ]} />
      <p className="text-xs text-slate-500">
        Consumed = quantity per part × received quantity of the line. &ldquo;At subcontractor&rdquo; is the supplier&apos;s total stock of the component at the
        line&apos;s plant, across all of its subcontracting orders.
      </p>
      {data.atSubcontractor.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">Stock at the subcontractor by batch</summary>
          <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
            {data.atSubcontractor.map((s, i) => (
              <li key={`${s.material}-${s.plant}-${s.batch}-${i}`} className="flex flex-wrap justify-between gap-2 px-3 py-1.5">
                <span>{s.material ?? '–'} · plant {s.plant}{s.batch ? ` · batch ${s.batch}` : ''}</span>
                <span className="tabular-nums">{qty(s.qty)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {open && (
        <div className="flex flex-wrap gap-2">
          {data.lines.map((l) => <Button key={l.line} variant="primary" onClick={() => setProviding(l.line)}>Provide components · line {l.line}</Button>)}
        </div>
      )}
      {canProvide && !PROVIDABLE.includes(po.status) && <p className="text-xs text-slate-500">Components are provided while the order is released and open for receipt.</p>}
      {!canProvide && <p className="text-xs text-slate-500">Components are provided to the subcontractor by the receiver (stores) role.</p>}
      {providing !== null && (
        <ProvideDialog po={po} lineNo={providing} rows={rows.filter((r) => r.line === providing)} onClose={() => setProviding(null)} />
      )}
    </div>
  );
}

type ProvideResult = { po: string; line: number; subcontractor: string; components: { material: string; qty: string; batch: string; from: string }[] };

function ProvideDialog({ po, lineNo, rows, onClose }: { po: LifecyclePo; lineNo: number; rows: ComponentRow[]; onClose: () => void }) {
  const line = po.lines.find((l) => l.line_no === lineNo);
  const [sloc, setSloc] = useState('0001');
  const [drafts, setDrafts] = useState(() => rows.map((r) => ({ material: r.material, qty: String(r.outstanding || Number(r.qty)), batch: '' })));
  const chosen = drafts.filter((d) => Number(d.qty) > 0);
  const invalid = drafts.some((d) => d.qty.trim() !== '' && (Number.isNaN(Number(d.qty)) || Number(d.qty) < 0));
  const provide = useCommand(() => api.post<ProvideResult>(`/purchase-orders/${encodeURIComponent(po.number)}/components`, {
    line: lineNo, storage_location: sloc.trim() || '0001',
    components: chosen.map((d) => ({ material: d.material, qty: d.qty, batch: d.batch.trim() })),
  }), {
    success: (r) => `${r.components.length} component(s) transferred to ${r.subcontractor} (541)`,
    onSuccess: onClose,
  });
  const update = (i: number, patch: Partial<(typeof drafts)[number]>) => setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  return (
    <Dialog open title={`Provide components · ${po.number} line ${lineNo}`} onClose={onClose}>
      {line && <p className="text-sm text-slate-600">{line.description} · ordered {qty(line.qty, line.uom)} · received {qty(line.received_qty)}</p>}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field label="Issue from storage location" hint={line?.plant ? `Plant ${line.plant}; own unrestricted stock` : 'Own unrestricted stock'}>
          {(id) => <Input id={id} maxLength={10} value={sloc} onChange={(e) => setSloc(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-2 py-2">Component</th><th className="px-2 py-2 text-right">Planned / provided</th><th className="px-2 py-2">Provide qty</th><th className="px-2 py-2">Batch</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {drafts.map((d, i) => {
              const r = rows[i];
              return (
                <tr key={d.material} className="align-top">
                  <td className="px-2 py-2"><p className="font-medium">{r.material}</p><p className="text-xs text-slate-500">{r.description}</p></td>
                  <td className="px-2 py-2 text-right tabular-nums">{qty(r.qty, r.uom)} / {qty(r.provided)}</td>
                  <td className="px-2 py-2"><Input aria-label={`Quantity of ${r.material}`} inputMode="decimal" value={d.qty} onChange={(e) => update(i, { qty: e.target.value })} className="w-28" /></td>
                  <td className="px-2 py-2"><Input aria-label={`Batch of ${r.material}`} value={d.batch} onChange={(e) => update(i, { batch: e.target.value })} className="w-28" /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        The default is what is still to be provided against the plan. Components with quantity 0 are skipped. Stock moves from your storage location to the
        subcontractor (541); short own stock is refused.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!chosen.length || invalid} busy={provide.isPending} onClick={() => provide.mutate()}>Transfer to subcontractor</Button>
      </div>
    </Dialog>
  );
}

export const isSubcontracting = (po: LifecyclePo) => po.lines.some((l) => l.purchase_type === 'SUBCONTRACTING');
