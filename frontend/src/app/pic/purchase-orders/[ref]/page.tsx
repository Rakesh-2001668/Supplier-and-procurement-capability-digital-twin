'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Dialog, Facts, Input, StatusChip, Textarea } from '@/components/pic/ui';
import { api, readSessionUser } from '@/lib/pic/api';
import { date, inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { emptyEway, EwayFields, ewayPayload, ewayProblem } from '../../receiving/_components';
import { ScheduleConfirmDialog, ScheduleTab, TransmissionsTab } from './_ops';
import { RetentionTab } from './_retention';

type PoLine = { id: string; line_no: number; description: string; qty: string; uom: string; unit_price_minor: number; net_minor: number;
  need_date: string; price_source: string; purchase_type: string; shipped_qty: string; received_qty: string; accepted_qty: string;
  rejected_qty: string; invoiced_qty: string; gr_required: boolean; ses_required: boolean; quality_managed: boolean };
type Po = {
  id: string; number: string; status: string; version: number; row_version?: number; supplier: { code: string; name: string }; total_minor: number;
  payment_terms: string; incoterms: string | null; tolerance: { over_pct?: string; under_pct?: string; price_pct?: string };
  purpose_code: string; plant: string; released_by: string | null; erp_doc_no: string | null; rule_set_version: string;
  retention_pct?: string | null; lineageChain: string[]; lines: PoLine[];
  validation: { riskScore: number | null; touchless: boolean | null; factors: { code: string; points: number; evidence: string }[]; reasons: string[] };
};

export default function PurchaseOrderPage() {
  const { ref } = useParams<{ ref: string }>();
  const { data: po, isLoading, error } = useApi<Po>(`/purchase-orders/${ref}`);
  const roles = readSessionUser()?.roles ?? [];
  const supplier = roles.includes('SUPPLIER_USER');
  const buyer = roles.includes('BUYER');
  const [dialog, setDialog] = useState<'change' | 'asn' | 'confirm' | null>(null);
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
            {supplier && po.status === 'TRANSMITTED' && <Button variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}>Confirm order</Button>}
            {supplier && po.status === 'TRANSMITTED' && <Button onClick={() => setDialog('confirm')}>Confirm with dates</Button>}
            {supplier && ['CONFIRMED', 'PARTIALLY_RECEIVED'].includes(po.status) && !services && <Button variant="primary" onClick={() => setDialog('asn')}>Send ASN</Button>}
            {!supplier && ['RELEASED', 'TRANSMITTED', 'CONFIRMED'].includes(po.status) && <Button onClick={() => setDialog('change')}>Change order</Button>}
          </>
        )}
        facts={po && (
          <div className="space-y-4">
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
    </>
  );
}

function ChangeOrderDialog({ po, onClose }: { po: Po; onClose: () => void }) {
  const line = po.lines[0];
  const [qtyValue, setQty] = useState(line.qty);
  const [needDate, setNeedDate] = useState(line.need_date);
  const [reason, setReason] = useState('');
  const change = useCommand(() => api.post(`/purchase-orders/${po.number}/versions`,
    { changes: [{ line: line.line_no, qty: qtyValue, need_date: needDate }], reason }),
  { success: 'New PO version sent for supplier re-confirmation', onSuccess: onClose });
  return (
    <Dialog open title={`Change ${po.number} (creates version ${po.version + 1})`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs font-medium">Quantity (line {line.line_no})<Input value={qtyValue} onChange={(e) => setQty(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium">Need date<Input type="date" value={needDate} onChange={(e) => setNeedDate(e.target.value)} /></label>
        <label className="flex flex-col gap-1 text-xs font-medium md:col-span-2">Reason<Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </div>
      <p className="mt-3 text-xs text-slate-500">The supplier must re-confirm the new version. Changes are validated and risk-scored again.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!reason} busy={change.isPending} onClick={() => change.mutate()}>Send change</Button>
      </div>
    </Dialog>
  );
}

function AsnDialog({ po, onClose }: { po: Po; onClose: () => void }) {
  const line = po.lines[0];
  const open = Number(line.qty) - Number(line.shipped_qty);
  const today = new Date().toISOString().slice(0, 10);
  const [shipQty, setShipQty] = useState(String(open));
  const [batch, setBatch] = useState('');
  const [expected, setExpected] = useState(today);
  const [eway, setEway] = useState(emptyEway);
  const [coc, setCoc] = useState('');
  const send = useCommand(() => api.post('/asns', {
    po: po.number, ship_date: today, expected_date: expected, ...ewayPayload(eway), documents: coc ? [coc] : [],
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
