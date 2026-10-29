'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Dialog, Facts, Field, Input, StatusChip, Textarea } from '@/components/pic/ui';
import { api, readSessionUser } from '@/lib/pic/api';
import { date, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { isPositive, today } from '../../invoices/_components';
import { emptyEway, EwayFields, ewayPayload, ewayProblem } from '../../receiving/_components';
import {
  CancelPoDialog, CANCELLABLE, CLOSABLE, ClosePoDialog, ifMatch, isSubcontracting, RESUBMITTABLE, ResubmitPoDialog, SHORT_CLOSABLE, ShortClosePoDialog,
  SubcontractingTab,
} from './_lifecycle';
import { ScheduleConfirmDialog, ScheduleTab, TransmissionsTab } from './_ops';
import { RetentionTab } from './_retention';

type PoLine = { id: string; line_no: number; description: string; qty: string; uom: string; unit_price_minor: number; net_minor: number;
  need_date: string; price_source: string; purchase_type: string; shipped_qty: string; received_qty: string; accepted_qty: string;
  rejected_qty: string; invoiced_qty: string; invoiced_minor: number; ses_approved_minor: number; plant: string; gr_required: boolean;
  ses_required: boolean; quality_managed: boolean };
type Po = {
  id: string; number: string; status: string; version: number; row_version?: number; supplier: { code: string; name: string }; total_minor: number;
  payment_terms: string; incoterms: string | null; tolerance: { over_pct?: string; under_pct?: string; price_pct?: string };
  purpose_code: string; plant: string; released_by: string | null; erp_doc_no: string | null; rule_set_version: string;
  retention_pct?: string | null; lineageChain: string[]; lines: PoLine[];
  validation: { riskScore: number | null; touchless: boolean | null; factors: { code: string; points: number; evidence: string }[]; reasons: string[] };
  awaitingConfirmation?: boolean;
  pendingChangeApproval?: { role: string; evidence: { fromVersion?: number; toTotalMinor?: number; triggers?: string[]; reason?: string } } | null;
};

// Change orders (services/order.py SM "change"); a partly received order is changed down to, never below, the received quantity.
const CHANGEABLE = ['RELEASED', 'TRANSMITTED', 'CONFIRMED', 'PARTIALLY_RECEIVED'];

export default function PurchaseOrderPage() {
  const { ref } = useParams<{ ref: string }>();
  const { data: po, isLoading, error } = useApi<Po>(`/purchase-orders/${ref}`);
  const roles = readSessionUser()?.roles ?? [];
  const supplier = roles.includes('SUPPLIER_USER');
  const buyer = roles.includes('BUYER');
  const [dialog, setDialog] = useState<'change' | 'asn' | 'confirm' | 'cancel' | 'close' | 'shortclose' | 'resubmit' | null>(null);
  const confirm = useCommand(() => api.post(`/purchase-orders/${ref}/confirmations`, { status: 'CONFIRMED' }), { success: 'Order confirmed' });
  const services = po?.lines.every((l) => l.ses_required);

  return (
    <>
      <ObjectPage
        type="PURCHASE_ORDER" docRef={ref} eyebrow="PO-02 · Purchase order" loading={isLoading} error={error}
        title={<>{po?.number} <span className="text-base font-normal text-slate-500">v{po?.version} · {po?.supplier.name}</span></>}
        status={po?.status}
        actions={po && (
          <>
            {supplier && (po.status === 'TRANSMITTED' || po.awaitingConfirmation) && <Button variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}>Confirm order</Button>}
            {supplier && (po.status === 'TRANSMITTED' || po.awaitingConfirmation) && <Button onClick={() => setDialog('confirm')}>Confirm with dates</Button>}
            {supplier && ['CONFIRMED', 'PARTIALLY_RECEIVED'].includes(po.status) && !services && <Button variant="primary" onClick={() => setDialog('asn')}>Send ASN</Button>}
            {buyer && CHANGEABLE.includes(po.status) && !po.pendingChangeApproval && <Button onClick={() => setDialog('change')}>Change order</Button>}
            {buyer && RESUBMITTABLE.includes(po.status) && <Button variant="primary" onClick={() => setDialog('resubmit')}>Correct and re-submit</Button>}
            {buyer && CLOSABLE.includes(po.status) && <Button onClick={() => setDialog('close')}>Close order</Button>}
            {buyer && SHORT_CLOSABLE.includes(po.status) && <Button onClick={() => setDialog('shortclose')}>Short-close</Button>}
            {buyer && CANCELLABLE.includes(po.status) && <Button variant="danger" onClick={() => setDialog('cancel')}>Cancel order</Button>}
          </>
        )}
        facts={po && (
          <div className="space-y-4">
            {po.pendingChangeApproval && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="status">
                A change of version {po.pendingChangeApproval.evidence.fromVersion ?? po.version} awaits approval by{' '}
                {po.pendingChangeApproval.role.replace(/_/g, ' ').toLowerCase()}
                {po.pendingChangeApproval.evidence.triggers?.length ? ` (${po.pendingChangeApproval.evidence.triggers.map((t) => t.replace(/_/g, ' ').toLowerCase()).join(', ')})` : ''}
                {po.pendingChangeApproval.evidence.toTotalMinor !== undefined ? ` · new value ${inr(po.pendingChangeApproval.evidence.toTotalMinor)}` : ''}.
                The version in force stays with the supplier until it is approved.
              </p>
            )}
            <Facts items={[
              ['Net value', inr(po.total_minor)], ['Payment terms', po.payment_terms], ['Incoterms', po.incoterms ?? '–'],
              ['Tolerance', `+${po.tolerance.over_pct ?? 0}% / −${po.tolerance.under_pct ?? 0}%`], ['Purpose', po.purpose_code], ['Plant', po.plant],
              ['Released by', po.released_by ?? '–'], ['ERP document', po.erp_doc_no ?? 'not posted yet'],
              ['Retention', Number(po.retention_pct ?? 0) > 0 ? `${Number(po.retention_pct)}% withheld per invoice` : 'none'],
            ]} />
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">AI validation (explainable)</p>
              <p className="mt-1 text-sm">
                Risk score <span className="font-semibold">{po.validation.riskScore ?? '–'}/100</span> ·{' '}
                {po.validation.touchless ? <span className="text-emerald-700">touchless criteria met (DMN-02)</span> : <span className="text-amber-700">routed for approval</span>}
              </p>
              {po.validation.factors.length > 0 && (
                <ul className="mt-1 text-sm text-slate-700">{po.validation.factors.map((f) => <li key={f.code}>+{f.points} {f.code.replace(/_/g, ' ').toLowerCase()} — {f.evidence}</li>)}</ul>
              )}
              {po.validation.reasons.length > 0 && <p className="mt-1 text-sm text-slate-600">Why not touchless: {po.validation.reasons.join('; ')}</p>}
              <p className="mt-1 text-xs text-slate-500">Lineage: {po.lineageChain.join(' → ') || '–'} · Rules {po.rule_set_version}</p>
            </div>
          </div>
        )}
        extraTabs={po ? [
          { id: 'schedule', label: 'Schedule', content: <ScheduleTab po={po} canEdit={buyer} /> },
          { id: 'transmissions', label: 'Transmissions', content: <TransmissionsTab po={po} canResend={buyer} /> },
          ...(isSubcontracting(po) && !supplier ? [{ id: 'components', label: 'Subcontracting',
            content: <SubcontractingTab po={po} canProvide={roles.includes('RECEIVER')} /> }] : []),
          ...(Number(po.retention_pct ?? 0) > 0 && !supplier ? [{ id: 'retention', label: 'Retention',
            content: <RetentionTab poNumber={po.number} canRelease={roles.includes('AP_CLERK') || roles.includes('FINANCE_CONTROLLER')} /> }] : []),
        ] : []}
        lines={po && (
          <DataTable<PoLine> rows={po.lines} columns={[
            { key: 'line_no', header: 'Line' },
            { key: 'description', header: 'Item' },
            { key: 'purchase_type', header: 'Type', render: (l) => l.purchase_type.toLowerCase() },
            { key: 'qty', header: 'Ordered', align: 'right', render: (l) => qty(l.qty, l.uom) },
            { key: 'unit_price_minor', header: 'Price', align: 'right', render: (l) => inr(l.unit_price_minor) },
            { key: 'price_source', header: 'Price source', render: (l) => <StatusChip status={l.price_source} /> },
            { key: 'need_date', header: 'Need', render: (l) => date(l.need_date) },
            { key: 'shipped_qty', header: 'Shipped', align: 'right', render: (l) => qty(l.shipped_qty) },
            { key: 'accepted_qty', header: 'Accepted', align: 'right', render: (l) => `${qty(l.accepted_qty)}${Number(l.rejected_qty) ? ` (−${qty(l.rejected_qty)})` : ''}` },
            { key: 'invoiced_qty', header: 'Invoiced', align: 'right', render: (l) => qty(l.invoiced_qty) },
          ]} />
        )}
      />
      {po && dialog === 'change' && <ChangeOrderDialog po={po} onClose={() => setDialog(null)} />}
      {po && dialog === 'asn' && <AsnDialog po={po} onClose={() => setDialog(null)} />}
      {po && dialog === 'confirm' && <ScheduleConfirmDialog po={po} onClose={() => setDialog(null)} />}
      {po && dialog === 'cancel' && <CancelPoDialog po={po} onClose={() => setDialog(null)} />}
      {po && dialog === 'close' && <ClosePoDialog po={po} onClose={() => setDialog(null)} />}
      {po && dialog === 'shortclose' && <ShortClosePoDialog po={po} onClose={() => setDialog(null)} />}
      {po && dialog === 'resubmit' && <ResubmitPoDialog po={po} onClose={() => setDialog(null)} />}
    </>
  );
}

type ChangeResult = { po: string; version: number; status: string; approval?: string; chain?: string[]; proposedVersion?: number };

function ChangeOrderDialog({ po, onClose }: { po: Po; onClose: () => void }) {
  const [drafts, setDrafts] = useState(() => po.lines.map((l) => ({ line: l.line_no, qty: String(Number(l.qty)), price: String(l.unit_price_minor / 100),
    needDate: l.need_date })));
  const [reason, setReason] = useState('');
  const [deviationReason, setDeviationReason] = useState('');
  const changes = drafts.flatMap((d) => {
    const line = po.lines.find((l) => l.line_no === d.line);
    if (!line) return [];
    const change: Record<string, string | number> = { line: d.line };
    if (Number(d.qty) !== Number(line.qty)) change.qty = d.qty.trim();
    if (Math.round(Number(d.price) * 100) !== line.unit_price_minor) change.unit_price = d.price.trim();
    if (d.needDate !== line.need_date) change.need_date = d.needDate;
    return Object.keys(change).length > 1 ? [change] : [];
  });
  const invalid = drafts.some((d) => !isPositive(d.qty) || !isPositive(d.price) || !d.needDate);
  const belowReceived = drafts.filter((d) => Number(d.qty) < Number(po.lines.find((l) => l.line_no === d.line)?.received_qty ?? 0)).map((d) => d.line);
  const priced = changes.some((c) => 'unit_price' in c);
  // If-Match: the change is refused (412) when the order changed since this page loaded.
  const change = useCommand(() => api.post<ChangeResult>(`/purchase-orders/${encodeURIComponent(po.number)}/versions`,
    { changes, reason: reason.trim(), deviationReason: priced && deviationReason.trim() ? deviationReason.trim() : undefined }, { ifMatch: ifMatch(po) }), {
    success: (r) => (r.approval === 'PENDING'
      ? `Change sent for approval (${(r.chain ?? []).map((c) => c.replace(/_/g, ' ').toLowerCase()).join(' → ')}); version ${r.proposedVersion} goes to the supplier once approved`
      : `Version ${r.version} sent to the supplier for re-confirmation`),
    onSuccess: onClose,
  });
  const update = (i: number, patch: Partial<(typeof drafts)[number]>) => setDrafts((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  return (
    <Dialog open title={`Change ${po.number} (creates version ${po.version + 1})`} onClose={onClose}>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-2 py-2">Line</th><th className="px-2 py-2">Quantity</th><th className="px-2 py-2">Unit price (₹)</th><th className="px-2 py-2">Need date</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {drafts.map((d, i) => {
              const line = po.lines[i];
              return (
                <tr key={d.line} className="align-top">
                  <td className="px-2 py-2"><p className="font-medium">{d.line} · {line.description}</p>
                    {Number(line.received_qty) > 0 && <p className="text-xs text-slate-500">received {qty(line.received_qty, line.uom)}</p>}</td>
                  <td className="px-2 py-2"><Input aria-label={`Quantity of line ${d.line}`} inputMode="decimal" className="w-28" value={d.qty} onChange={(e) => update(i, { qty: e.target.value })} /></td>
                  <td className="px-2 py-2"><Input aria-label={`Unit price of line ${d.line}`} inputMode="decimal" className="w-28" value={d.price} onChange={(e) => update(i, { price: e.target.value })} /></td>
                  <td className="px-2 py-2"><Input aria-label={`Need date of line ${d.line}`} type="date" value={d.needDate} onChange={(e) => update(i, { needDate: e.target.value })} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-3 grid gap-3">
        <Field label="Reason (sent with the new version and audited)">{(id) => <Textarea id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        {priced && (
          <Field label="Deviation reason" hint="Required when the new price is outside the contract tolerance (P07); such a change is approved before it is sent">
            {(id) => <Textarea id={id} maxLength={500} value={deviationReason} onChange={(e) => setDeviationReason(e.target.value)} />}
          </Field>
        )}
      </div>
      {belowReceived.length > 0 && (
        <p className="mt-2 text-xs text-amber-700" role="status">Line(s) {belowReceived.join(', ')}: the quantity cannot go below what was already received.</p>
      )}
      <p className="mt-3 text-xs text-slate-500">
        The supplier must re-confirm the new version. Changes are validated and risk-scored again; a price deviation (or a value rising into a higher
        approval band, where configured) is approved first and only then sent.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!reason.trim() || !changes.length || invalid || belowReceived.length > 0} busy={change.isPending}
          onClick={() => change.mutate()}>Send change</Button>
      </div>
    </Dialog>
  );
}

function AsnDialog({ po, onClose }: { po: Po; onClose: () => void }) {
  const line = po.lines[0];
  const open = Number(line.qty) - Number(line.shipped_qty);
  const shipDate = today();
  const [shipQty, setShipQty] = useState(String(open));
  const [batch, setBatch] = useState('');
  const [expected, setExpected] = useState(shipDate);
  const [eway, setEway] = useState(emptyEway);
  const [coc, setCoc] = useState('');
  const send = useCommand(() => api.post('/asns', {
    po: po.number, ship_date: shipDate, expected_date: expected, ...ewayPayload(eway), documents: coc ? [coc] : [],
    lines: [{ line: line.line_no, qty: shipQty, batches: batch ? [{ batch, qty: shipQty }] : [] }],
  }), { success: 'ASN sent', onSuccess: onClose });
  return (
    <Dialog open title={`Advance shipping notice for ${po.number}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs font-medium">Quantity (open {open})<Input value={shipQty} onChange={(e) => setShipQty(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium">Batch<Input value={batch} onChange={(e) => setBatch(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium">Expected arrival<Input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium md:col-span-2">Certificate of conformity reference<Input value={coc} onChange={(e) => setCoc(e.target.value)} /></label>
      </div>
      <div className="mt-3"><EwayFields value={eway} onChange={setEway} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!!ewayProblem(eway)} busy={send.isPending} onClick={() => send.mutate()}>Send ASN</Button>
      </div>
    </Dialog>
  );
}
