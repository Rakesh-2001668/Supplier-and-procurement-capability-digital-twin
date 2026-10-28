'use client';

import { useState } from 'react';
import { Button, Dialog, Empty, Field, Input, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { isNumber, isPositive, minus, PoDetail, PoLine, today } from '../invoices/_components';

export type InspectionLot = { id: string; number: string; gr: string; gr_id: string; qty: string; sample_size: number; status: string;
  accepted_qty: string | null; rejected_qty: string | null; defect_code: string | null; usage_decision: string | null; created_at: string };

// ---------------------------------------------------------------- post goods receipt (RCV-01/02)
type GrDraft = { line: PoLine; qty: string; batch: string; expiry: string; serials: string; storage_location: string };

// Serial numbers are entered comma- or line-separated (implants, serial-managed materials).
const serialList = (text: string) => text.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);

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
      line: l, qty: asn ? minus(l.shipped_qty, l.received_qty) : minus(l.qty, l.received_qty), batch: '', expiry: '', serials: '',
      storage_location: l.storage_location ?? '0001',
    })));
  }

  const chosen = lines.filter((l) => isPositive(l.qty));
  const invalid = lines.some((l) => !isNumber(l.qty) || Number(l.qty) < 0);
  const post = useCommand(() => api.post<{ number: string; status: string; warnings?: GrWarning[] }>('/goods-receipts', {
    po, asn: asn || undefined, delivery_note: deliveryNote.trim() || undefined, posting_date: postingDate,
    lines: chosen.map((l) => ({ line: l.line.line_no, qty: l.qty, batch: l.batch.trim(), storage_location: l.storage_location.trim() || undefined,
      expiry: l.expiry || undefined, serials: serialList(l.serials) })),
  }), {
    success: (r) => `${r.number} posted · ${r.status.replace(/_/g, ' ').toLowerCase()}${r.warnings?.length ? ` · warning: ${r.warnings.map((w) => w.detail).join('; ')}` : ''}`,
    onSuccess: onClose,
  });
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
                <tr><th className="px-2 py-2">PO line</th><th className="px-2 py-2">Receive qty</th><th className="px-2 py-2">Batch / lot</th><th className="px-2 py-2">Expiry</th><th className="px-2 py-2">Serials</th><th className="px-2 py-2">Storage loc.</th></tr>
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
                    <td className="px-2 py-2"><Input type="date" aria-label={`Expiry line ${l.line.line_no}`} value={l.expiry} onChange={(e) => update(i, { expiry: e.target.value })} className="w-36" /></td>
                    <td className="px-2 py-2"><Input aria-label={`Serial numbers line ${l.line.line_no}`} value={l.serials} onChange={(e) => update(i, { serials: e.target.value })} placeholder="SN-001, SN-002" className="w-40" />
                      {serialList(l.serials).length > 0 && <p className="mt-1 text-xs text-slate-500">{serialList(l.serials).length} serial(s)</p>}</td>
                    <td className="px-2 py-2"><Input aria-label={`Storage location line ${l.line.line_no}`} value={l.storage_location} onChange={(e) => update(i, { storage_location: e.target.value })} className="w-20" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Over-delivery beyond the PO tolerance is blocked. Quality-managed lines are posted to quality stock and an inspection lot is opened; consignment lines go to supplier-owned consignment stock. Lot-controlled materials (e.g. implants) need the lot, the expiry date and one serial per unit; expired lots are refused. Lines with quantity 0 are skipped.
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

// ---------------------------------------------------------------- e-way bill on ASNs (TD §12.3, rule EWAY-BILL)
export type GrWarning = { code: string; asn: string; ewayBillNo: string | null; validUntil: string; receivedAt: string; detail: string };
export type EwayDraft = { ewayBillNo: string; vehicleNo: string; validUntil: string; distanceKm: string };
export const emptyEway: EwayDraft = { ewayBillNo: '', vehicleNo: '', validUntil: '', distanceKm: '' };

/** ASN body fields. The validity is the end of the given day (IST); without it the API computes it from the distance. */
export function ewayPayload(d: EwayDraft) {
  return {
    eway_bill_no: d.ewayBillNo.trim() || undefined,
    vehicle_no: d.vehicleNo.trim() || undefined,
    eway_bill_valid_until: d.validUntil ? `${d.validUntil}T23:59:59+05:30` : undefined,
    distance_km: !d.validUntil && isPositive(d.distanceKm) ? Math.round(Number(d.distanceKm)) : undefined,
  };
}

export function ewayProblem(d: EwayDraft): string | null {
  if (d.ewayBillNo.trim() && !/^\d{12}$/.test(d.ewayBillNo.trim())) return 'The e-way bill number has 12 digits';
  if (d.distanceKm.trim() && !isPositive(d.distanceKm)) return 'Distance must be a positive number of kilometres';
  return null;
}

export function EwayFields({ value, onChange }: { value: EwayDraft; onChange: (next: EwayDraft) => void }) {
  const set = (patch: Partial<EwayDraft>) => onChange({ ...value, ...patch });
  const problem = ewayProblem(value);
  return (
    <fieldset className="rounded-lg border border-slate-200 p-3">
      <legend className="px-1 text-xs font-semibold text-slate-700">E-way bill</legend>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="E-way bill no. (12 digits)">
          {(id) => <Input id={id} inputMode="numeric" maxLength={12} value={value.ewayBillNo} onChange={(e) => set({ ewayBillNo: e.target.value.replace(/\s/g, '') })} />}
        </Field>
        <Field label="Vehicle no.">
          {(id) => <Input id={id} maxLength={15} placeholder="e.g. TN45AB1234" value={value.vehicleNo} onChange={(e) => set({ vehicleNo: e.target.value.toUpperCase() })} />}
        </Field>
        <Field label="Valid until (end of day)">
          {(id) => <Input id={id} type="date" value={value.validUntil} onChange={(e) => set({ validUntil: e.target.value })} />}
        </Field>
        <Field label="or distance (km)" hint="Validity is then one day per 200 km">
          {(id) => <Input id={id} inputMode="numeric" disabled={!!value.validUntil} value={value.distanceKm} onChange={(e) => set({ distanceKm: e.target.value })} />}
        </Field>
      </div>
      <p className="mt-2 text-xs text-slate-500">Required when the consignment value including GST reaches the e-way bill threshold: number, vehicle and validity (after the ship date).</p>
      {problem && <p className="mt-1 text-xs text-amber-700" role="status">{problem}</p>}
    </fieldset>
  );
}

/** E-way bill cell for ASN lists: number, vehicle and validity, flagged once expired. */
export function EwayCell({ asn }: { asn: { eway_bill_no: string | null; vehicle_no?: string | null; eway_bill_valid_until?: string | null } }) {
  if (!asn.eway_bill_no) return <span className="text-slate-500">–</span>;
  const expired = !!asn.eway_bill_valid_until && new Date(asn.eway_bill_valid_until) < new Date();
  return (
    <div className="text-xs">
      <p className="font-mono text-sm">{asn.eway_bill_no}</p>
      <p className="text-slate-500">{asn.vehicle_no ?? 'no vehicle'}{asn.eway_bill_valid_until ? ` · until ${dateTime(asn.eway_bill_valid_until)}` : ''}</p>
      {expired && <StatusChip status="EXPIRED" />}
    </div>
  );
}

/** Warnings returned with a goods receipt (e.g. received after the e-way bill expired; audited). */
export function GrWarnings({ warnings }: { warnings?: GrWarning[] }) {
  if (!warnings?.length) return null;
  return (
    <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      {warnings.map((w) => <p key={w.code + w.asn}><span className="font-semibold">{w.code.replace(/_/g, ' ').toLowerCase()}:</span> {w.detail}</p>)}
    </div>
  );
}
