'use client';

import { useState } from 'react';
import { Button, Dialog, Empty, Field, Input, Loading, ProblemBox, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { isNumber, isPositive, minus, PoDetail, PoLine, today } from '../invoices/_components';

export type InspectionLot = { id: string; number: string; gr: string; gr_id: string; qty: string; sample_size: number; status: string;
  accepted_qty: string | null; rejected_qty: string | null; defect_code: string | null; usage_decision: string | null; created_at: string };

// ---------------------------------------------------------------- post goods receipt (RCV-01/02)
type GrDraft = { line: PoLine; qty: string; batch: string; storage_location: string };

export function GoodsReceiptDialog({ po, asn, onClose }: { po: string; asn?: string; onClose: () => void }) {
  const { data, isLoading, error } = useApi<PoDetail>(`/purchase-orders/${encodeURIComponent(po)}`);
  const [lines, setLines] = useState<GrDraft[]>([]);
  const [deliveryNote, setDeliveryNote] = useState('');
  const [postingDate, setPostingDate] = useState(today());

  // Goods lines only (service lines are confirmed by service entry sheet).
  // Default qty: shipped-not-received when receiving an ASN, otherwise ordered-not-received.
  const [prefilled, setPrefilled] = useState(false);
  if (data && !prefilled) {
    setPrefilled(true);
    setLines(data.lines.filter((l) => l.gr_required && !l.ses_required).map((l) => ({
      line: l, qty: asn ? minus(l.shipped_qty, l.received_qty) : minus(l.qty, l.received_qty), batch: '',
      storage_location: l.storage_location ?? '0001',
    })));
  }

  const chosen = lines.filter((l) => isPositive(l.qty));
  const invalid = lines.some((l) => !isNumber(l.qty) || Number(l.qty) < 0);
  const post = useCommand(() => api.post<{ number: string; status: string }>('/goods-receipts', {
    po, asn: asn || undefined, delivery_note: deliveryNote.trim() || undefined, posting_date: postingDate,
    lines: chosen.map((l) => ({ line: l.line.line_no, qty: l.qty, batch: l.batch.trim(), storage_location: l.storage_location.trim() || undefined })),
  }), { success: (r) => `${r.number} posted · ${r.status.replace(/_/g, ' ').toLowerCase()}`, onSuccess: onClose });
  const update = (i: number, patch: Partial<GrDraft>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  return (
    <Dialog open title={`Post goods receipt · ${po}${asn ? ` / ${asn}` : ' (no ASN)'}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Delivery note">
          {(id) => <Input id={id} value={deliveryNote} onChange={(e) => setDeliveryNote(e.target.value)} placeholder="Supplier delivery note no." />}
        </Field>
        <Field label="Posting date">
          {(id) => <Input id={id} type="date" required value={postingDate} onChange={(e) => setPostingDate(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-4">
        {isLoading ? <Loading text="Loading PO lines…" /> : error ? <ProblemBox error={error} /> : !lines.length ? (
          <Empty title="No goods lines to receive" hint="Service lines are confirmed through a service entry sheet." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-2 py-2">PO line</th><th className="px-2 py-2">Receive qty</th><th className="px-2 py-2">Batch</th><th className="px-2 py-2">Storage loc.</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {lines.map((l, i) => (
                  <tr key={l.line.id} className="align-top">
                    <td className="px-2 py-2">
                      <p className="font-medium">{l.line.line_no} · {l.line.description}</p>
                      <p className="text-xs text-slate-500">
                        Ordered {qty(l.line.qty, l.line.uom)} · shipped {qty(l.line.shipped_qty)} · received {qty(l.line.received_qty)}
                        {l.line.quality_managed && ' · goes to quality stock (inspection lot)'}
                      </p>
                    </td>
                    <td className="px-2 py-2"><Input aria-label={`Receive quantity line ${l.line.line_no}`} value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} className="w-28" /></td>
                    <td className="px-2 py-2"><Input aria-label={`Batch line ${l.line.line_no}`} value={l.batch} onChange={(e) => update(i, { batch: e.target.value })} className="w-28" /></td>
                    <td className="px-2 py-2"><Input aria-label={`Storage location line ${l.line.line_no}`} value={l.storage_location} onChange={(e) => update(i, { storage_location: e.target.value })} className="w-20" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Over-delivery beyond the PO tolerance is blocked. Quality-managed lines are posted to quality stock and an inspection lot is opened; lines with quantity 0 are skipped.
        {asn && ' The default quantity is what was shipped and not yet received on this PO.'}
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!chosen.length || invalid || !postingDate} busy={post.isPending} onClick={() => post.mutate()}>Post goods receipt</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- usage decision (RCV-03)
const DEFECT_CODES = ['POROSITY', 'DIMENSIONAL', 'SURFACE', 'CRACK', 'MATERIAL_CERT', 'PACKAGING', 'WRONG_PART'];

export function UsageDecisionDialog({ lot, onClose }: { lot: InspectionLot; onClose: () => void }) {
  const [accepted, setAccepted] = useState(String(Number(lot.qty)));
  const [rejected, setRejected] = useState('0');
  const [defect, setDefect] = useState('');
  const [reason, setReason] = useState('');
  const numeric = isNumber(accepted) && isNumber(rejected) && Number(accepted) >= 0 && Number(rejected) >= 0;
  const balanced = numeric && Math.abs(Number(accepted) + Number(rejected) - Number(lot.qty)) < 1e-9;
  const rejecting = numeric && Number(rejected) > 0;
  const missing = rejecting && (!defect.trim() || !reason.trim());
  const decide = useCommand(() => api.post<{ status: string; returnDelivery: string | null }>(`/inspection-lots/${encodeURIComponent(lot.number)}/usage-decision`, {
    accepted, rejected, defect_code: rejecting ? defect.trim().toUpperCase() : undefined, reason: rejecting ? reason.trim() : undefined,
  }), {
    success: (r) => `Usage decision recorded · ${r.status.replace(/_/g, ' ').toLowerCase()}${r.returnDelivery ? ` · return ${r.returnDelivery} created` : ''}`,
    onSuccess: onClose,
  });
  const setAcc = (v: string) => { setAccepted(v); if (isNumber(v)) setRejected(minus(lot.qty, v)); };
  return (
    <Dialog open title={`Usage decision · ${lot.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">Lot quantity <span className="font-semibold">{qty(lot.qty)}</span> from {lot.gr} · inspect sample of {lot.sample_size} (ISO 2859-1, level II).</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field label="Accepted quantity">{(id) => <Input id={id} value={accepted} onChange={(e) => setAcc(e.target.value)} />}</Field>
        <Field label="Rejected quantity">{(id) => <Input id={id} value={rejected} onChange={(e) => setRejected(e.target.value)} />}</Field>
        {rejecting && (
          <>
            <Field label="Defect code (required when rejecting)">
              {(id) => <>
                <Input id={id} list={`${id}-codes`} value={defect} onChange={(e) => setDefect(e.target.value)} />
                <datalist id={`${id}-codes`}>{DEFECT_CODES.map((c) => <option key={c} value={c} />)}</datalist>
              </>}
            </Field>
            <div className="md:col-span-2">
              <Field label="Reason (required when rejecting)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
            </div>
          </>
        )}
      </div>
      {!balanced && <p className="mt-2 text-xs text-amber-700" role="status">Accepted + rejected must equal the lot quantity {qty(lot.qty)}.</p>}
      {balanced && missing && <p className="mt-2 text-xs text-amber-700" role="status">Rejections need a defect code and a reason.</p>}
      <p className="mt-3 text-xs text-slate-500">Accepted stock moves to unrestricted (321). Rejected stock is blocked (350) and returned to the supplier (122) with a credit note requested.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!balanced || missing} busy={decide.isPending} onClick={() => decide.mutate()}>Record decision</Button>
      </div>
    </Dialog>
  );
}
