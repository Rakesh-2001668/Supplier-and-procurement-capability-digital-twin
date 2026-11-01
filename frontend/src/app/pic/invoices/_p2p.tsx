'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, isPositive, today, useSessionUser } from './_components';

// ---------------------------------------------------------------- debit notes (BP M10)
export type DebitNoteLine = { kind: 'PRICE' | 'CHARGE'; invoice_line?: number; qty?: string; unitDebitMinor?: number; charge?: string; description?: string;
  netMinor: number; taxMinor: number; gstRate: string };
export type DebitNote = { id: string; number: string; supplierDebitNoteNo: string; invoice: string; noteDate: string; reason: string; status: string;
  netMinor: number; taxMinor: number; grossMinor: number; retentionMinor: number; lines: DebitNoteLine[]; erpDocument: string | null; paymentStatus: string;
  match: { findings?: { kind: string; detail: string }[] }; approvals: { role: string; status: string; decision: string | null; comment: string | null }[] };
type InvLine = { id: string; line_no: number; description: string; qty: string; unit_price_minor: number; gst_rate: string };
type InvoiceForDebit = { id: string; number: string; status: string; supplier: { code: string; name: string }; lines: InvLine[] };

const CHARGES = ['FREIGHT', 'PACKING', 'INSURANCE', 'INSPECTION', 'HANDLING', 'OTHER'];

function lineText(l: DebitNoteLine) {
  return l.kind === 'PRICE' ? `line ${l.invoice_line}: ${qty(l.qty)} × ${inr(l.unitDebitMinor)} price correction` : `${label(l.charge)} charge ${inr(l.netMinor)}`;
}

/** Debit notes of an invoice with the matching result, approvals and the AP actions (approve, post, reject). */
export function DebitNotesPanel({ invoiceId, invoiceStatus, canRaise }: { invoiceId: string; invoiceStatus: string; canRaise: boolean }) {
  const user = useSessionUser();
  const notes = useApi<DebitNote[]>(`/invoices/${invoiceId}/debit-notes`);
  const [raising, setRaising] = useState(false);
  const [rejecting, setRejecting] = useState<DebitNote | null>(null);
  const ap = hasRole(user, 'AP_CLERK');
  const approver = hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER');
  const approve = useCommand((n: DebitNote) => api.post(`/debit-notes/${n.id}/approve`), { success: 'Debit note approved for posting' });
  const post = useCommand((n: DebitNote) => api.post<{ status: string; erpDocument?: string }>(`/debit-notes/${n.id}/post`), {
    success: (r) => (r.erpDocument ? `Posted to the ERP as debit memo ${r.erpDocument}` : `Posting ${r.status.toLowerCase()}`),
  });
  if (notes.isLoading) return <Loading />;
  if (notes.error) return <ProblemBox error={notes.error} />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">
          An upward price correction or additional charge raised by the supplier. It is matched against the order, approved, posted to the ERP as a vendor
          debit memo and added to the payment of the invoice.
        </p>
        {canRaise && !['REJECTED'].includes(invoiceStatus) && <Button variant="primary" onClick={() => setRaising(true)}>Raise debit note</Button>}
      </div>
      {!notes.data?.length ? <Empty title="No debit notes" /> : notes.data.map((n) => (
        <div key={n.id} className="rounded-lg border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold">{n.number}</span><StatusChip status={n.status} />
              {n.status === 'POSTED' && <StatusChip status={n.paymentStatus} />}
              <span className="text-xs text-slate-500">dated {date(n.noteDate)}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {approver && n.status === 'MATCHED' && <Button variant="primary" busy={approve.isPending} onClick={() => approve.mutate(n)}>Approve</Button>}
              {ap && n.status === 'APPROVED' && <Button variant="primary" busy={post.isPending} onClick={() => post.mutate(n)}>Post to ERP</Button>}
              {approver && ['RECEIVED', 'MATCHED', 'APPROVED'].includes(n.status) && <Button variant="danger" onClick={() => setRejecting(n)}>Reject</Button>}
            </div>
          </div>
          <p className="mt-2 text-sm">{n.reason}</p>
          <ul className="mt-1 list-disc pl-5 text-sm text-slate-700">{n.lines.map((l, i) => <li key={i}>{lineText(l)} · tax {inr(l.taxMinor)}</li>)}</ul>
          <p className="mt-2 text-sm">Net {inr(n.netMinor)} · GST {inr(n.taxMinor)} · <span className="font-semibold">gross {inr(n.grossMinor)}</span>
            {n.retentionMinor ? ` · retention ${inr(n.retentionMinor)}` : ''}{n.erpDocument ? ` · ERP debit memo ${n.erpDocument}` : ''}</p>
          {n.status === 'PENDING_APPROVAL' && (
            <div role="status" className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-semibold">Outside the order: waiting for {n.approvals.map((a) => label(a.role)).join(' → ') || 'the buyer'}</p>
              <ul className="list-disc pl-5">{(n.match.findings ?? []).map((f, i) => <li key={i}>{f.detail}</li>)}</ul>
            </div>
          )}
          {n.status === 'MATCHED' && <p className="mt-2 text-xs text-slate-500">Within the order price; accounts payable approves it for posting.</p>}
        </div>
      ))}
      {raising && <RaiseDebitNoteDialog invoiceId={invoiceId} onClose={() => setRaising(false)} />}
      {rejecting && <RejectDebitNoteDialog note={rejecting} onClose={() => setRejecting(null)} />}
    </div>
  );
}

function RejectDebitNoteDialog({ note, onClose }: { note: DebitNote; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const reject = useCommand(() => api.post(`/debit-notes/${note.id}/reject`, { reason: reason.trim() }), { success: `${note.number} rejected`, onSuccess: onClose });
  return (
    <Dialog open title={`Reject ${note.number}`} onClose={onClose}>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={reason.trim().length < 3} busy={reject.isPending} onClick={() => reject.mutate()}>Reject debit note</Button>
      </div>
    </Dialog>
  );
}

/** Supplier (portal) or accounts payable (on the supplier's behalf): price correction per invoice line and/or one additional charge. */
export function RaiseDebitNoteDialog({ invoiceId, onClose }: { invoiceId: string; onClose: () => void }) {
  const { data: inv, isLoading, error } = useApi<InvoiceForDebit>(`/invoices/${invoiceId}`);
  const [noteNo, setNoteNo] = useState('');
  const [noteDate, setNoteDate] = useState(today());
  const [reason, setReason] = useState('');
  const [qtys, setQtys] = useState<Record<number, string>>({});
  const [units, setUnits] = useState<Record<number, string>>({});
  const [charge, setCharge] = useState('');
  const [chargeKind, setChargeKind] = useState('FREIGHT');
  const [chargeText, setChargeText] = useState('');
  const [chargeRate, setChargeRate] = useState('18');
  const priced = (inv?.lines ?? []).filter((l) => isPositive(qtys[l.line_no] ?? '') && isPositive(units[l.line_no] ?? ''));
  const tooMuch = priced.some((l) => Number(qtys[l.line_no]) > Number(l.qty));
  const hasCharge = isPositive(charge);
  const body = () => ({
    supplier_debit_note_no: noteNo.trim(), note_date: noteDate, reason: reason.trim(),
    lines: [
      ...priced.map((l) => ({ kind: 'PRICE', invoice_line: l.line_no, qty: qtys[l.line_no], unit_debit_minor: rupeesToMinor(units[l.line_no]) })),
      ...(hasCharge ? [{ kind: 'CHARGE', charge: chargeKind, description: chargeText.trim() || undefined, amount_minor: rupeesToMinor(charge), gst_rate: chargeRate }] : []),
    ],
  });
  const send = useCommand(() => api.post<DebitNote>(`/invoices/${invoiceId}/debit-notes`, body()), {
    success: (r) => `Debit note ${r.number} ${r.status === 'PENDING_APPROVAL' ? 'sent to the buyer for approval' : 'matched'} · ${inr(r.grossMinor)}`,
    onSuccess: onClose,
  });
  const gross = priced.reduce((s, l) => s + Number(qtys[l.line_no]) * Number(units[l.line_no]) * (1 + Number(l.gst_rate) / 100), 0)
    + (hasCharge ? Number(charge) * (1 + Number(chargeRate || 0) / 100) : 0);
  return (
    <Dialog open title={`Raise debit note${inv ? ` against ${inv.number}` : ''}`} onClose={onClose}>
      {isLoading && <Loading />}
      {error && <ProblemBox error={error} />}
      {inv && (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Debit note number *">{(id) => <Input id={id} value={noteNo} maxLength={30} onChange={(e) => setNoteNo(e.target.value)} />}</Field>
            <Field label="Date">{(id) => <Input id={id} type="date" max={today()} value={noteDate} onChange={(e) => setNoteDate(e.target.value)} />}</Field>
            <Field label="Reason *">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. price revised to the PO price" />}</Field>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium text-slate-700">Price correction per invoice line (₹ added per unit)</p>
            {inv.lines.map((l) => (
              <div key={l.id} className="mb-2 grid gap-2 md:grid-cols-[1fr_8rem_10rem] md:items-end">
                <p className="text-sm">{l.line_no} · {l.description}<span className="block text-xs text-slate-500">invoiced {qty(l.qty)} at {inr(l.unit_price_minor)}</span></p>
                <Field label="Quantity">{(id) => <Input id={id} value={qtys[l.line_no] ?? ''} onChange={(e) => setQtys((q) => ({ ...q, [l.line_no]: e.target.value }))} />}</Field>
                <Field label="Debit per unit (₹)">{(id) => <Input id={id} value={units[l.line_no] ?? ''} onChange={(e) => setUnits((q) => ({ ...q, [l.line_no]: e.target.value }))} />}</Field>
              </div>
            ))}
          </div>
          <div className="grid gap-2 md:grid-cols-4 md:items-end">
            <Field label="Additional charge">{(id) => <Select id={id} value={chargeKind} onChange={(e) => setChargeKind(e.target.value)} options={CHARGES.map((c) => ({ value: c, label: label(c) }))} />}</Field>
            <Field label="Amount before GST (₹)">{(id) => <Input id={id} value={charge} onChange={(e) => setCharge(e.target.value)} />}</Field>
            <Field label="GST %">{(id) => <Input id={id} value={chargeRate} onChange={(e) => setChargeRate(e.target.value)} />}</Field>
            <Field label="Description">{(id) => <Input id={id} value={chargeText} onChange={(e) => setChargeText(e.target.value)} />}</Field>
          </div>
          {tooMuch && <p role="alert" className="text-sm text-red-700">A quantity cannot exceed the invoiced quantity.</p>}
          <p className="text-right text-sm">Debit incl. GST ≈ <span className="font-semibold">{inr(Math.round(gross * 100))}</span></p>
          <p className="text-xs text-slate-500">A price correction within the order price is matched at once; anything above it, and every additional charge, goes to the buyer for approval.</p>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" busy={send.isPending} disabled={!noteNo.trim() || reason.trim().length < 3 || tooMuch || (!priced.length && !hasCharge)}
              onClick={() => send.mutate()}>Raise debit note</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- early payment and supply-chain finance (BP M10)
type Offer = { id: string; kind: 'DISCOUNT' | 'SCF'; source: string; status: string; discountPct: string; discountMinor: number; payOn: string | null;
  originalDue: string | null; expiresOn: string; annualisedPct: string | null; note: string | null; erpDocument: string | null };
type EarlyState = { eligible: boolean; reason: string | null; paymentOption: string; discountMinor: number; dueDate: string | null; payableMinor: number;
  termsDiscount: { pct: string; until: string; available: boolean } | null; maxDiscountPct: string; scfEnabled: boolean; scfMinInvoiceMinor: number; offers: Offer[] };

export function EarlyPaymentPanel({ invoiceId }: { invoiceId: string }) {
  const user = useSessionUser();
  const supplierSide = hasRole(user, 'SUPPLIER_USER');
  const buyerSide = hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER');
  const state = useApi<EarlyState>(`/invoices/${invoiceId}/early-payment`);
  const [offering, setOffering] = useState(false);
  const terms = useCommand(() => api.post<Offer>(`/invoices/${invoiceId}/early-payment/offers`, { source: 'TERMS' }), { success: 'Terms discount taken; the invoice is paid on the next run' });
  const scf = useCommand(() => api.post<Offer>(`/invoices/${invoiceId}/scf`, {}), { success: 'Supply-chain finance elected; the financing programme is notified' });
  const decide = useCommand((a: { id: string; accept: boolean }) => api.post(`/invoices/${invoiceId}/early-payment/offers/${a.id}/decision`, { accept: a.accept }),
    { success: 'Decision recorded' });
  const cancel = useCommand((id: string) => api.post(`/invoices/${invoiceId}/early-payment/offers/${id}/cancel`, {}), { success: 'Offer withdrawn' });
  if (state.isLoading) return <Loading />;
  if (state.error) return <ProblemBox error={state.error} />;
  const s = state.data!;
  const mine = (o: Offer) => (o.source === 'SUPPLIER') === supplierSide;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Pay a posted invoice earlier at a discount (dynamic discounting), or let the supplier be financed on it by the supply-chain-finance programme.
        An accepted discount moves the due date to the pay-on date and reduces the payment; if the payment run misses that date the offer lapses.
      </p>
      <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <div><dt className="text-xs text-slate-500">Payment option</dt><dd className="font-medium">{label(s.paymentOption)}</dd></div>
        <div><dt className="text-xs text-slate-500">Due date</dt><dd className="font-medium">{date(s.dueDate)}</dd></div>
        <div><dt className="text-xs text-slate-500">Payable now</dt><dd className="font-medium">{inr(s.payableMinor)}</dd></div>
        <div><dt className="text-xs text-slate-500">Accepted discount</dt><dd className="font-medium">{s.discountMinor ? inr(s.discountMinor) : '–'}</dd></div>
      </dl>
      {!s.eligible && <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{s.reason}</p>}
      {s.eligible && (
        <div className="flex flex-wrap gap-2">
          {buyerSide && s.termsDiscount?.available && (
            <Button busy={terms.isPending} onClick={() => terms.mutate()}>Take terms discount ({s.termsDiscount.pct}% until {date(s.termsDiscount.until)})</Button>
          )}
          {(buyerSide || supplierSide) && <Button variant="primary" onClick={() => setOffering(true)}>{supplierSide ? 'Ask to be paid early' : 'Offer early payment'}</Button>}
          {s.scfEnabled && (buyerSide || supplierSide) && <Button busy={scf.isPending} onClick={() => scf.mutate()}>Elect supply-chain finance</Button>}
        </div>
      )}
      <DataTable<Offer> rows={s.offers} empty="No offers or elections" columns={[
        { key: 'kind', header: 'Type', render: (o) => (o.kind === 'SCF' ? 'Supply-chain finance' : 'Discount') },
        { key: 'source', header: 'From', render: (o) => label(o.source) },
        { key: 'status', header: 'Status', render: (o) => <StatusChip status={o.status} /> },
        { key: 'discountMinor', header: 'Discount', align: 'right', render: (o) => (o.kind === 'SCF' ? '–' : `${inr(o.discountMinor)} (${o.discountPct}%)`) },
        { key: 'annualisedPct', header: 'Annualised', align: 'right', render: (o) => (o.annualisedPct ? `${o.annualisedPct}%` : '–') },
        { key: 'payOn', header: 'Pay on', render: (o) => date(o.payOn) },
        { key: 'action', header: '', render: (o) => o.status === 'OFFERED' ? (
          <div className="flex gap-2">
            {!mine(o) && <><Button variant="primary" busy={decide.isPending} onClick={() => decide.mutate({ id: o.id, accept: true })}>Accept</Button>
              <Button variant="danger" busy={decide.isPending} onClick={() => decide.mutate({ id: o.id, accept: false })}>Decline</Button></>}
            {mine(o) && <Button busy={cancel.isPending} onClick={() => cancel.mutate(o.id)}>Withdraw</Button>}
          </div>
        ) : null },
      ]} />
      {offering && <OfferDialog invoiceId={invoiceId} state={s} supplierSide={supplierSide} onClose={() => setOffering(false)} />}
    </div>
  );
}

function OfferDialog({ invoiceId, state, supplierSide, onClose }: { invoiceId: string; state: EarlyState; supplierSide: boolean; onClose: () => void }) {
  const [pct, setPct] = useState('');
  const [payOn, setPayOn] = useState('');
  const [note, setNote] = useState('');
  const send = useCommand(() => api.post<Offer>(`/invoices/${invoiceId}/early-payment/offers`, { discountPct: pct, payOn, note: note.trim() || undefined }),
    { success: (r) => `Offer made: ${inr(r.discountMinor)} if paid on ${date(r.payOn)}`, onSuccess: onClose });
  return (
    <Dialog open title={supplierSide ? 'Ask to be paid early' : 'Offer early payment'} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={`Discount % (max ${state.maxDiscountPct})`}>{(id) => <Input id={id} value={pct} onChange={(e) => setPct(e.target.value)} />}</Field>
        <Field label="Pay on" hint={`Before ${date(state.dueDate)}`}>{(id) => <Input id={id} type="date" min={today()} value={payOn} onChange={(e) => setPayOn(e.target.value)} />}</Field>
        <div className="md:col-span-2"><Field label="Note">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field></div>
      </div>
      <p className="mt-2 text-xs text-slate-500">The other party accepts or declines; the offer expires after the validity set in rule EARLY-PAYMENT.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={send.isPending} disabled={!isPositive(pct) || !payOn} onClick={() => send.mutate()}>{supplierSide ? 'Send request' : 'Send offer'}</Button>
      </div>
    </Dialog>
  );
}

export function ScfBadge({ option }: { option: string | null | undefined }) {
  if (!option || option === 'STANDARD') return <span>Standard</span>;
  return <StatusChip status={option === 'SCF' ? 'SCF' : 'EARLY_DISCOUNT'} />;
}
