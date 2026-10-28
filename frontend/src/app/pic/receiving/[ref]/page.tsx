'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Dialog, Facts, Field, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, PoDetail, useSessionUser } from '../../invoices/_components';
import { GrWarning, GrWarnings, InspectionLot, UsageDecisionDialog } from '../_components';

type GrLine = { id: string; line_no: number; po_line_id: string; qty: string; accepted_qty: string; rejected_qty: string; batch: string;
  serials: string[]; expiry: string | null; stock_type: string; storage_location: string; movement_type: string };
type ReturnDelivery = { id: string; number: string; po_line_id: string; qty: string; reason: string; replacement_required: boolean;
  credit_note_expected: boolean; status: string; created_at: string };
type Node = { type: string; id: string; ref: string };
type Gr = { id: string; number: string; po_id: string; asn_id: string | null; status: string; posting_date: string; delivery_note: string | null;
  reversal_of: string | null; created_at: string; updated_at: string | null; lines: GrLine[]; inspectionLots: Omit<InspectionLot, 'gr'>[];
  returns: ReturnDelivery[]; lineage: { nodes: Node[] }; warnings?: GrWarning[] };

const REVERSIBLE = ['POSTED', 'ACCEPTED', 'QUALITY_HOLD'];

export default function GoodsReceiptPage() {
  const { ref } = useParams<{ ref: string }>();
  const user = useSessionUser();
  const { data: gr, isLoading, error } = useApi<Gr>(`/goods-receipts/${encodeURIComponent(decodeURIComponent(ref))}`);
  // The GR read model carries ids only; the PO and ASN numbers come from its lineage nodes.
  const poNumber = gr?.lineage.nodes.find((n) => n.type === 'PURCHASE_ORDER' && n.id === gr.po_id)?.ref;
  const asnNumber = gr?.asn_id ? gr.lineage.nodes.find((n) => n.type === 'ASN' && n.id === gr.asn_id)?.ref : undefined;
  const { data: po } = useApi<PoDetail>(poNumber ? `/purchase-orders/${encodeURIComponent(poNumber)}` : null);
  const poLine = (id: string) => po?.lines.find((l) => l.id === id);
  const [dialog, setDialog] = useState<'reverse' | null>(null);
  const [lot, setLot] = useState<InspectionLot | null>(null);
  const canReverse = hasRole(user, 'RECEIVER') && !!gr && REVERSIBLE.includes(gr.status);
  const canDecide = hasRole(user, 'QUALITY_INSPECTOR');

  return (
    <>
      <ObjectPage
        type="GOODS_RECEIPT" docRef={gr?.number ?? ''} eyebrow="RCV-02 · Goods receipt" loading={isLoading} error={error}
        title={<>{gr?.number} {po && <span className="text-base font-normal text-slate-500">{po.supplier.name}</span>}</>}
        status={gr?.status}
        actions={canReverse && <Button variant="danger" onClick={() => setDialog('reverse')}>Reverse</Button>}
        facts={gr && (
          <div className="space-y-3">
          <GrWarnings warnings={gr.warnings} />
          <Facts items={[
            ['Purchase order', poNumber ? <Link key="po" className="text-[#1A56DB] hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(poNumber)}`}>{poNumber}</Link> : '–'],
            ['ASN', asnNumber ?? (gr.asn_id ? 'linked' : 'received without ASN')],
            ['Delivery note', gr.delivery_note ?? '–'], ['Posting date', date(gr.posting_date)],
            ['Supplier', po ? `${po.supplier.code} · ${po.supplier.name}` : '–'],
            ['Inspection lots', String(gr.inspectionLots.length)], ['Return deliveries', String(gr.returns.length)],
            ['Last change', dateTime(gr.updated_at ?? gr.created_at)],
          ]} />
          </div>
        )}
        lines={gr && (
          <DataTable<GrLine> rows={gr.lines} columns={[
            { key: 'line_no', header: 'Line' },
            { key: 'po_line', header: 'PO line / item', render: (l) => {
              const p = poLine(l.po_line_id);
              return p ? <>{p.line_no} · {p.description}</> : '–';
            } },
            { key: 'qty', header: 'Received', align: 'right', render: (l) => qty(l.qty, poLine(l.po_line_id)?.uom) },
            { key: 'accepted_qty', header: 'Accepted', align: 'right', render: (l) => qty(l.accepted_qty) },
            { key: 'rejected_qty', header: 'Rejected', align: 'right', render: (l) => Number(l.rejected_qty)
              ? <span className="font-semibold text-red-700">{qty(l.rejected_qty)}</span> : qty(l.rejected_qty) },
            { key: 'batch', header: 'Batch', render: (l) => l.batch || '–' },
            { key: 'expiry', header: 'Expiry', render: (l) => l.expiry || '–' },
            { key: 'serials', header: 'Serials', render: (l) => l.serials?.length ? <span className="font-mono text-xs">{l.serials.join(', ')}</span> : '–' },
            { key: 'storage_location', header: 'Sloc' },
            { key: 'stock_type', header: 'Stock type', render: (l) => <StatusChip status={l.stock_type} /> },
            { key: 'movement_type', header: 'Mvt', render: (l) => <span className="font-mono text-xs">{l.movement_type}</span> },
          ]} />
        )}
        extraTabs={gr ? [
          { id: 'inspection', label: `Inspection lots (${gr.inspectionLots.length})`, content: (
            <DataTable<Omit<InspectionLot, 'gr'>> rows={gr.inspectionLots} empty="Not quality-managed: no inspection lot" columns={[
              { key: 'number', header: 'Lot' },
              { key: 'qty', header: 'Lot qty', align: 'right', render: (l) => qty(l.qty) },
              { key: 'sample_size', header: 'Sample', align: 'right' },
              { key: 'status', header: 'Status', render: (l) => <StatusChip status={l.status} /> },
              { key: 'usage_decision', header: 'Decision', render: (l) => l.usage_decision ? <StatusChip status={l.usage_decision} /> : '–' },
              { key: 'accepted_qty', header: 'Accepted', align: 'right', render: (l) => qty(l.accepted_qty) },
              { key: 'rejected_qty', header: 'Rejected', align: 'right', render: (l) => qty(l.rejected_qty) },
              { key: 'defect_code', header: 'Defect', render: (l) => l.defect_code ?? '–' },
              { key: 'action', header: '', render: (l) => canDecide && l.status === 'OPEN'
                ? <Button variant="primary" onClick={() => setLot({ ...l, gr: gr.number })}>Usage decision</Button> : null },
            ]} />
          ) },
          { id: 'returns', label: `Returns (${gr.returns.length})`, content: (
            <DataTable<ReturnDelivery> rows={gr.returns} empty="No return deliveries" columns={[
              { key: 'number', header: 'Return delivery' },
              { key: 'po_line', header: 'PO line', render: (r) => poLine(r.po_line_id)?.line_no ?? '–' },
              { key: 'qty', header: 'Qty', align: 'right', render: (r) => qty(r.qty) },
              { key: 'reason', header: 'Reason' },
              { key: 'follow', header: 'Follow-up', render: (r) => [r.credit_note_expected && 'credit note expected', r.replacement_required && 'replacement required']
                .filter(Boolean).join(', ') || '–' },
              { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
              { key: 'created_at', header: 'Created', render: (r) => date(r.created_at) },
            ]} />
          ) },
        ] : []}
      />
      {gr && dialog === 'reverse' && <ReverseDialog gr={gr} onClose={() => setDialog(null)} />}
      {lot && <UsageDecisionDialog lot={lot} onClose={() => setLot(null)} />}
    </>
  );
}

function ReverseDialog({ gr, onClose }: { gr: Gr; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const reverse = useCommand(() => api.post<{ number: string; status: string }>(`/goods-receipts/${encodeURIComponent(gr.number)}/reverse`, { reason: reason.trim() }), {
    success: (r) => `${r.number} ${r.status.toLowerCase()}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Reverse ${gr.number}`} onClose={onClose}>
      <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">
        Reversal (movement 102) takes the received quantity back out of stock and reduces the PO&apos;s received and accepted quantities.
        Receipts that are already invoiced and posted cannot be reversed — use a return delivery instead.
      </div>
      <div className="mt-3">
        <Field label="Reason (required)">
          {(id) => <Textarea id={id} required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Posted against the wrong PO" />}
        </Field>
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" className="h-4 w-4" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
        I confirm this receipt should be reversed
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={!reason.trim() || !confirmed} busy={reverse.isPending} onClick={() => reverse.mutate()}>Reverse receipt</Button>
      </div>
    </Dialog>
  );
}
