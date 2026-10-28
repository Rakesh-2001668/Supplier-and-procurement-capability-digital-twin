'use client';

import { useState } from 'react';
import { Button, Card, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { isNumber, isPositive, minus, PoDetail, today } from '../invoices/_components';
import { emptyEway, EwayFields, ewayPayload, ewayProblem } from '../receiving/_components';

const rupees = (minor: number) => (minor / 100).toFixed(2);

// ---------------------------------------------------------------- propose change (PO confirmation with CHANGE_REQUESTED)
export function ProposeChangeDialog({ po, onClose }: { po: PoDetail; onClose: () => void }) {
  const [lines, setLines] = useState(po.lines.map((l) => ({ line: l, qty: String(Number(l.qty)), need_date: l.need_date })));
  const [note, setNote] = useState('');
  const changes = lines.map((l) => {
    const change: { line: number; qty?: string; need_date?: string } = { line: l.line.line_no };
    if (isNumber(l.qty) && Number(l.qty) !== Number(l.line.qty)) change.qty = l.qty;
    if (l.need_date && l.need_date !== l.line.need_date) change.need_date = l.need_date;
    return change;
  }).filter((c) => c.qty !== undefined || c.need_date !== undefined);
  const invalid = lines.some((l) => !isPositive(l.qty));
  const send = useCommand(() => api.post<{ confirmation?: string; status: string; outsideTolerance?: string[] }>(
    `/purchase-orders/${encodeURIComponent(po.number)}/confirmations`, { status: 'CHANGE_REQUESTED', lines: changes, note: note.trim() }), {
    success: (r) => r.confirmation === 'CHANGE_REQUESTED'
      ? `Change proposal sent to the buyer${r.outsideTolerance?.length ? `: ${r.outsideTolerance.join('; ')}` : ''}`
      : 'Changes are within tolerance — order confirmed',
    onSuccess: onClose,
  });
  const update = (i: number, patch: { qty?: string; need_date?: string }) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <Dialog open title={`Propose change to ${po.number} v${po.version}`} onClose={onClose}>
      <div className="space-y-3">
        {lines.map((l, i) => (
          <div key={l.line.id} className="grid gap-3 rounded-lg border border-slate-200 p-3 md:grid-cols-3">
            <div className="text-sm">
              <p className="font-medium">Line {l.line.line_no}</p>
              <p className="text-slate-600">{l.line.description}</p>
              <p className="text-xs text-slate-500">Ordered {qty(l.line.qty, l.line.uom)} by {date(l.line.need_date)}</p>
            </div>
            <Field label="Quantity you can deliver">{(id) => <Input id={id} value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} />}</Field>
            <Field label="Date you can deliver">{(id) => <Input id={id} type="date" value={l.need_date} onChange={(e) => update(i, { need_date: e.target.value })} />}</Field>
          </div>
        ))}
        <Field label="Note to the buyer (required)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
      <p className="mt-3 text-xs text-slate-500">Changes within the PO tolerance are accepted automatically; anything outside goes back to the buyer for review.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!changes.length || invalid || !note.trim()} busy={send.isPending} onClick={() => send.mutate()}>Send proposal</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- advance shipping notice (multi-line)
export function AsnDialog({ po, onClose }: { po: PoDetail; onClose: () => void }) {
  const goods = po.lines.filter((l) => l.gr_required && !l.ses_required);
  const [lines, setLines] = useState(goods.map((l) => ({ line: l, qty: minus(l.qty, l.shipped_qty), batch: '' })));
  const [shipDate, setShipDate] = useState(today());
  const [expected, setExpected] = useState(today());
  const [eway, setEway] = useState(emptyEway);
  const [coc, setCoc] = useState('');
  const chosen = lines.filter((l) => isPositive(l.qty));
  const send = useCommand(() => api.post<{ number: string }>('/asns', {
    po: po.number, ship_date: shipDate, expected_date: expected, ...ewayPayload(eway), documents: coc.trim() ? [coc.trim()] : [],
    lines: chosen.map((l) => ({ line: l.line.line_no, qty: l.qty, batches: l.batch.trim() ? [{ batch: l.batch.trim(), qty: l.qty }] : [] })),
  }), { success: (r) => `ASN ${r.number} sent`, onSuccess: onClose });
  const update = (i: number, patch: { qty?: string; batch?: string }) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <Dialog open title={`Advance shipping notice for ${po.number}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Ship date">{(id) => <Input id={id} type="date" value={shipDate} onChange={(e) => setShipDate(e.target.value)} />}</Field>
        <Field label="Expected arrival">{(id) => <Input id={id} type="date" value={expected} onChange={(e) => setExpected(e.target.value)} />}</Field>
        <Field label="Certificate of conformity reference">{(id) => <Input id={id} value={coc} onChange={(e) => setCoc(e.target.value)} />}</Field>
      </div>
      <div className="mt-3"><EwayFields value={eway} onChange={setEway} /></div>
      <div className="mt-4 space-y-2">
        {lines.map((l, i) => (
          <div key={l.line.id} className="grid gap-3 rounded-lg border border-slate-200 p-3 md:grid-cols-3">
            <div className="text-sm">
              <p className="font-medium">Line {l.line.line_no} · {l.line.description}</p>
              <p className="text-xs text-slate-500">Ordered {qty(l.line.qty, l.line.uom)} · already shipped {qty(l.line.shipped_qty)}</p>
            </div>
            <Field label="Quantity shipped">{(id) => <Input id={id} value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} />}</Field>
            <Field label="Batch">{(id) => <Input id={id} value={l.batch} onChange={(e) => update(i, { batch: e.target.value })} />}</Field>
          </div>
        ))}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!chosen.length || !shipDate || !expected || !!ewayProblem(eway)} busy={send.isPending} onClick={() => send.mutate()}>Send ASN</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- service entry sheet
const METHODS = ['TIME_MATERIAL', 'MILESTONE', 'UNIT_RATE', 'PROGRESS'];

function monthBounds() {
  const d = new Date();
  const first = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
  return [first.toISOString().slice(0, 10), last.toISOString().slice(0, 10)];
}

export function ServiceSheetDialog({ po, onClose }: { po: PoDetail; onClose: () => void }) {
  const services = po.lines.filter((l) => l.ses_required);
  const [from, to] = monthBounds();
  const [method, setMethod] = useState('TIME_MATERIAL');
  const [periodFrom, setPeriodFrom] = useState(from);
  const [periodTo, setPeriodTo] = useState(to);
  const [lines, setLines] = useState(services.map((l) => ({ line: l, description: l.description, qty: '', unit_rate: rupees(l.unit_price_minor) })));
  const chosen = lines.filter((l) => isPositive(l.qty));
  const total = chosen.reduce((s, l) => s + (isNumber(l.unit_rate) ? Math.round(Number(l.qty) * rupeesToMinor(l.unit_rate)) : 0), 0);
  const invalid = chosen.some((l) => !isPositive(l.unit_rate) || !l.description.trim()) || periodTo < periodFrom;
  const send = useCommand(() => api.post<{ number: string; status: string }>('/service-entries', {
    po: po.number, method, period_from: periodFrom, period_to: periodTo,
    lines: chosen.map((l) => ({ line: l.line.line_no, description: l.description.trim(), qty: l.qty, unit_rate: l.unit_rate })),
  }), { success: (r) => `${r.number} submitted for approval by the service owner`, onSuccess: onClose });
  const update = (i: number, patch: Partial<{ description: string; qty: string; unit_rate: string }>) =>
    setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <Dialog open title={`Service entry sheet for ${po.number}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Method">{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value)} options={METHODS.map((m) => ({ value: m, label: label(m) }))} />}</Field>
        <Field label="Period from">{(id) => <Input id={id} type="date" value={periodFrom} onChange={(e) => setPeriodFrom(e.target.value)} />}</Field>
        <Field label="Period to">{(id) => <Input id={id} type="date" value={periodTo} onChange={(e) => setPeriodTo(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 space-y-2">
        {lines.map((l, i) => (
          <div key={l.line.id} className="rounded-lg border border-slate-200 p-3">
            <p className="text-sm font-medium">Line {l.line.line_no} · {l.line.description}</p>
            <p className="text-xs text-slate-500">PO value {inr(l.line.net_minor)} · already approved {inr(l.line.ses_approved_minor)} · remaining {inr(l.line.net_minor - l.line.ses_approved_minor)}</p>
            <div className="mt-2 grid gap-3 md:grid-cols-3">
              <Field label="Description of work">{(id) => <Input id={id} value={l.description} onChange={(e) => update(i, { description: e.target.value })} />}</Field>
              <Field label={`Quantity (${l.line.uom})`}>{(id) => <Input id={id} value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} />}</Field>
              <Field label="Unit rate (₹)">{(id) => <Input id={id} value={l.unit_rate} onChange={(e) => update(i, { unit_rate: e.target.value })} />}</Field>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-right text-sm">Sheet value <span className="font-semibold">{inr(total)}</span></p>
      <p className="mt-1 text-xs text-slate-500">The sheet is submitted for approval by Axion&apos;s service owner; the approved value is what you can invoice.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!chosen.length || invalid} busy={send.isPending} onClick={() => send.mutate()}>Submit service sheet</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- sealed bid (RFQ)
type EventLine = { id: string; line_no: number; description: string; plant: string; annual_qty: string; monthly_qty: string; uom: string };
type SourcingEvent = { id: string; number: string; type: string; title: string; category: string; status: string; round: number; close_at: string;
  published_at: string | null; currency: string; lines: EventLine[]; criteria: { code: string; name: string; weight: number }[];
  bids: { supplier: string; round: number; status: string; submittedAt: string; hash: string }[] };
type BidDraft = { unit_price: string; freight: string; duty: string; packaging: string; payment_terms_days: string; lead_time_days: string; capacity_per_month: string };

export function BidDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const { data: event, isLoading, error } = useApi<SourcingEvent>(`/sourcing/events/${encodeURIComponent(number)}`);
  const [drafts, setDrafts] = useState<Record<number, BidDraft>>({});
  const [receipt, setReceipt] = useState<{ round: number; status: string; hash: string; submittedAt: string } | null>(null);
  const [prefilled, setPrefilled] = useState(false);
  if (event && !prefilled) {
    setPrefilled(true);
    setDrafts(Object.fromEntries(event.lines.map((l) => [l.line_no, { unit_price: '', freight: '0', duty: '0', packaging: '0',
      payment_terms_days: '60', lead_time_days: '', capacity_per_month: String(Number(l.monthly_qty)) }])));
  }
  const open = !!event && event.status === 'OPEN' && new Date(event.close_at) > new Date();
  const myRoundBid = event?.bids.find((b) => b.round === event.round);
  const entries = event?.lines.map((l) => ({ line: l, d: drafts[l.line_no] })).filter((e) => e.d) ?? [];
  const invalid = !entries.length || entries.some(({ d }) => !isPositive(d.unit_price) || !isNumber(d.freight) || !isNumber(d.duty) || !isNumber(d.packaging)
    || !isNumber(d.payment_terms_days) || !isPositive(d.lead_time_days) || (d.capacity_per_month !== '' && !isNumber(d.capacity_per_month)));
  const submit = useCommand(() => api.post<{ round: number; status: string; hash: string; submittedAt: string }>(`/sourcing/events/${encodeURIComponent(number)}/bids`, {
    lines: entries.map(({ line, d }) => ({ line: line.line_no, unit_price: d.unit_price, freight: d.freight || '0', duty: d.duty || '0', packaging: d.packaging || '0',
      payment_terms_days: Number(d.payment_terms_days), lead_time_days: Number(d.lead_time_days),
      capacity_per_month: d.capacity_per_month === '' ? undefined : d.capacity_per_month })),
  }), { success: 'Sealed bid submitted', onSuccess: setReceipt });
  const update = (line: number, patch: Partial<BidDraft>) => setDrafts((ds) => ({ ...ds, [line]: { ...ds[line], ...patch } }));

  return (
    <Dialog open title={`${number} · ${open ? 'Submit sealed bid' : 'Event details'}`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : event && (
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium">{event.title}</p>
            <p className="text-xs text-slate-600">{event.type} · {event.category} · round {event.round} · closes {dateTime(event.close_at)}</p>
            <div className="mt-1"><StatusChip status={event.status} /></div>
          </div>
          <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 text-sm text-slate-800">
            Bids are encrypted when you submit them and stay sealed until the event closes at <span className="font-semibold">{dateTime(event.close_at)}</span> —
            nobody at Axion can read prices before then. You can resubmit any time before close; your new bid replaces the previous one for this round.
          </div>
          {event.criteria.length > 0 && (
            <p className="text-xs text-slate-600">Evaluation: {event.criteria.map((c) => `${c.name} ${c.weight}%`).join(' · ')}</p>
          )}
          {(receipt || myRoundBid) && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" role="status">
              {receipt ? 'Bid received' : 'Your bid on file'} for round {(receipt ?? myRoundBid)!.round} · {label((receipt ?? myRoundBid)!.status)} ·
              {' '}{dateTime(receipt?.submittedAt ?? myRoundBid!.submittedAt)}
              <p className="mt-1 break-all font-mono text-[11px]">SHA-256 {receipt?.hash ?? myRoundBid!.hash}</p>
            </div>
          )}
          {event.bids.filter((b) => b.round !== event.round).map((b) => (
            <p key={b.round} className="text-xs text-slate-500">Round {b.round}: {label(b.status)} · {dateTime(b.submittedAt)}</p>
          ))}
          {open ? (
            <>
              {event.lines.map((l) => drafts[l.line_no] && (
                <div key={l.id} className="rounded-lg border border-slate-200 p-3">
                  <p className="text-sm font-medium">Line {l.line_no} · {l.description}</p>
                  <p className="text-xs text-slate-500">{qty(l.annual_qty, l.uom)} per year · {qty(l.monthly_qty, l.uom)} per month · plant {l.plant}</p>
                  <div className="mt-2 grid gap-3 md:grid-cols-4">
                    <Field label="Unit price (₹)">{(id) => <Input id={id} value={drafts[l.line_no].unit_price} onChange={(e) => update(l.line_no, { unit_price: e.target.value })} />}</Field>
                    <Field label="Freight / unit (₹)">{(id) => <Input id={id} value={drafts[l.line_no].freight} onChange={(e) => update(l.line_no, { freight: e.target.value })} />}</Field>
                    <Field label="Duty / unit (₹)">{(id) => <Input id={id} value={drafts[l.line_no].duty} onChange={(e) => update(l.line_no, { duty: e.target.value })} />}</Field>
                    <Field label="Packaging / unit (₹)">{(id) => <Input id={id} value={drafts[l.line_no].packaging} onChange={(e) => update(l.line_no, { packaging: e.target.value })} />}</Field>
                    <Field label="Payment terms (days)">{(id) => <Input id={id} inputMode="numeric" value={drafts[l.line_no].payment_terms_days} onChange={(e) => update(l.line_no, { payment_terms_days: e.target.value })} />}</Field>
                    <Field label="Lead time (days)">{(id) => <Input id={id} inputMode="numeric" value={drafts[l.line_no].lead_time_days} onChange={(e) => update(l.line_no, { lead_time_days: e.target.value })} />}</Field>
                    <Field label={`Capacity / month (${l.uom})`}>{(id) => <Input id={id} value={drafts[l.line_no].capacity_per_month} onChange={(e) => update(l.line_no, { capacity_per_month: e.target.value })} />}</Field>
                  </div>
                </div>
              ))}
              <div className="flex justify-end gap-2">
                <Button onClick={onClose}>Close</Button>
                <Button variant="primary" disabled={invalid} busy={submit.isPending} onClick={() => submit.mutate()}>
                  {myRoundBid || receipt ? 'Replace sealed bid' : 'Submit sealed bid'}
                </Button>
              </div>
            </>
          ) : (
            <>
              <ul className="text-sm text-slate-700">{event.lines.map((l) => <li key={l.id}>Line {l.line_no} · {l.description} · {qty(l.annual_qty, l.uom)} per year</li>)}</ul>
              <p className="text-sm text-slate-600">
                {event.status === 'PUBLISHED' ? 'Bidding opens once the event is opened by the buyer.' : 'Bidding is closed for this event.'}
              </p>
              <div className="flex justify-end"><Button onClick={onClose}>Close</Button></div>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- credit note against invoice exceptions
type InvException = { id: string; invoice_line_id: string | null; type: string; delta: Record<string, string | number>; detail: string; suggested_action: string; status: string };
type InvDetail = { id: string; number: string; status: string; lines: { id: string; line_no: number; description: string; qty: string; unit_price_minor: number; gst_rate: string }[];
  exceptions: InvException[]; creditNotes: { number: string; gross_minor: number; note_date: string }[] };

export function CreditNoteDialog({ invoiceId, onClose }: { invoiceId: string; onClose: () => void }) {
  const { data: inv, isLoading, error } = useApi<InvDetail>(`/invoices/${invoiceId}`);
  const [noteNo, setNoteNo] = useState('');
  const [noteDate, setNoteDate] = useState(today());
  const [reason, setReason] = useState('');
  const [qtys, setQtys] = useState<Record<number, string>>({});
  const open = (inv?.exceptions ?? []).filter((e) => e.status === 'OPEN' && ['QUANTITY', 'PRICE'].includes(e.type));
  const [prefilled, setPrefilled] = useState(false);
  if (inv && !prefilled) {
    setPrefilled(true);
    const defaults: Record<number, string> = {};
    for (const l of inv.lines) {
      const exc = inv.exceptions.find((e) => e.status === 'OPEN' && e.type === 'QUANTITY' && e.invoice_line_id === l.id);
      defaults[l.line_no] = exc?.delta?.qty !== undefined ? String(exc.delta.qty) : '';
    }
    setQtys(defaults);
    const first = inv.exceptions.find((e) => e.status === 'OPEN' && ['QUANTITY', 'PRICE'].includes(e.type));
    if (first) setReason((r) => r || first.detail);
  }
  const chosen = Object.entries(qtys).filter(([, v]) => isPositive(v));
  const amount = inv ? chosen.reduce((s, [line, v]) => {
    const l = inv.lines.find((x) => x.line_no === Number(line));
    return s + (l ? Math.round(Number(v) * l.unit_price_minor * (1 + Number(l.gst_rate) / 100)) : 0);
  }, 0) : 0;
  const send = useCommand(() => api.post<{ number: string }>(`/invoices/${invoiceId}/credit-notes`, {
    supplier_credit_note_no: noteNo.trim(), note_date: noteDate, reason: reason.trim(),
    lines: chosen.map(([line, v]) => ({ invoice_line: Number(line), qty: v })),
  }), { success: (r) => `Credit note ${r.number} issued — AP can now resolve the exception`, onSuccess: onClose });
  return (
    <Dialog open title={`Issue credit note${inv ? ` against ${inv.number}` : ''}`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : inv && (
        <div className="space-y-4">
          {open.length ? (
            <div className="space-y-2">
              {open.map((e) => (
                <Card key={e.id}>
                  <p className="text-sm"><span className="mr-2 rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-white">{e.type}</span>{e.detail}</p>
                  <p className="mt-1 text-xs text-slate-600">Axion asks: {e.suggested_action}</p>
                </Card>
              ))}
            </div>
          ) : <Empty title="No open quantity or price exceptions on this invoice" />}
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Your credit note number">{(id) => <Input id={id} required value={noteNo} onChange={(e) => setNoteNo(e.target.value)} />}</Field>
            <Field label="Credit note date">{(id) => <Input id={id} type="date" value={noteDate} onChange={(e) => setNoteDate(e.target.value)} />}</Field>
            <div className="md:col-span-2"><Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>
          </div>
          <div className="space-y-2">
            {inv.lines.map((l) => (
              <div key={l.id} className="grid items-end gap-3 md:grid-cols-3">
                <div className="text-sm md:col-span-2">
                  <p className="font-medium">Invoice line {l.line_no} · {l.description}</p>
                  <p className="text-xs text-slate-500">Invoiced {qty(l.qty)} at {inr(l.unit_price_minor)} + GST {l.gst_rate}%</p>
                </div>
                <Field label="Credit quantity">{(id) => <Input id={id} value={qtys[l.line_no] ?? ''} onChange={(e) => setQtys((q) => ({ ...q, [l.line_no]: e.target.value }))} />}</Field>
              </div>
            ))}
          </div>
          <p className="text-right text-sm">Credit incl. GST ≈ <span className="font-semibold">{inr(amount)}</span></p>
          {inv.creditNotes.length > 0 && <p className="text-xs text-slate-500">Already issued: {inv.creditNotes.map((n) => `${n.number} (${inr(n.gross_minor)})`).join(', ')}</p>}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!noteNo.trim() || !reason.trim() || !noteDate || !chosen.length} busy={send.isPending} onClick={() => send.mutate()}>Issue credit note</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- contracts: sign and redline
type Clause = { id: string; code: string; title: string; text: string; position: string; risk_score: number };
type ContractDetail = { number: string; title: string; status: string; valid_from: string; valid_to: string; target_value_minor: number; clauses: Clause[];
  signatures: { party: string; signer_name: string; signed_at: string }[] };

export function SignDialog({ number, defaultName, onClose }: { number: string; defaultName: string; onClose: () => void }) {
  const { data: c, isLoading, error } = useApi<ContractDetail>(`/contracts/${encodeURIComponent(number)}`);
  const [name, setName] = useState(defaultName);
  const [agree, setAgree] = useState(false);
  const sign = useCommand(() => api.post<{ signedBy: string[] }>(`/contracts/${encodeURIComponent(number)}/signatures`, { party: 'SUPPLIER', signer_name: name.trim() }), {
    success: (r) => `Signed · signatures on file: ${r.signedBy.map((p) => p.toLowerCase()).join(', ')}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Sign ${number}`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : c && (
        <div className="space-y-3">
          <p className="text-sm font-medium">{c.title}</p>
          <p className="text-xs text-slate-600">Valid {date(c.valid_from)} – {date(c.valid_to)} · target value {inr(c.target_value_minor)}</p>
          <ul className="max-h-60 space-y-2 overflow-y-auto rounded-lg border border-slate-200 p-3 text-sm">
            {c.clauses.map((cl) => <li key={cl.id}><span className="font-medium">{cl.title}.</span> {cl.text}</li>)}
          </ul>
          {c.signatures.length > 0 && <p className="text-xs text-slate-600">Signed: {c.signatures.map((s) => `${s.party.toLowerCase()} – ${s.signer_name}, ${dateTime(s.signed_at)}`).join('; ')}</p>}
          <Field label="Signer name and title">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            I am authorised to sign this contract on behalf of my company
          </label>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!name.trim() || !agree} busy={sign.isPending} onClick={() => sign.mutate()}>Sign contract</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

const POSITIONS = ['STANDARD', 'FALLBACK', 'NON_STANDARD'];

export function RedlineDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const { data: c, isLoading, error } = useApi<ContractDetail>(`/contracts/${encodeURIComponent(number)}`);
  const [code, setCode] = useState('');
  const [text, setText] = useState('');
  const [position, setPosition] = useState('FALLBACK');
  const clause = c?.clauses.find((x) => x.code === code);
  if (c?.clauses.length && !code) { setCode(c.clauses[0].code); setText(c.clauses[0].text); }
  const send = useCommand(() => api.post<{ code: string; risk_score: number }>(`/contracts/${encodeURIComponent(number)}/redlines`, { clause: code, text: text.trim(), position }), {
    success: (r) => `Redline on ${r.code} sent · playbook risk score ${r.risk_score}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Propose redline · ${number}`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : c && (
        <div className="space-y-3">
          <Field label="Clause">
            {(id) => <Select id={id} value={code} onChange={(e) => { setCode(e.target.value); setText(c.clauses.find((x) => x.code === e.target.value)?.text ?? ''); }}
              options={c.clauses.map((x) => ({ value: x.code, label: `${x.title} (${x.position.replace(/_/g, ' ').toLowerCase()})` }))} />}
          </Field>
          {clause && <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700"><span className="text-xs font-semibold uppercase text-slate-500">Current</span><br />{clause.text}</p>}
          <Field label="Proposed text">{(id) => <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} className="min-h-[120px]" />}</Field>
          <Field label="Position against Axion's playbook" hint="Non-standard positions need higher approval on Axion's side">
            {(id) => <Select id={id} value={position} onChange={(e) => setPosition(e.target.value)} options={POSITIONS.map((p) => ({ value: p, label: label(p) }))} />}
          </Field>
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!code || !text.trim() || text.trim() === clause?.text} busy={send.isPending} onClick={() => send.mutate()}>Send redline</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- change request on a confirmed order (PO-03)
/** After confirmation, qty/date changes go to the buyer as a change request; accepting it creates the next PO version. */
export function RequestChangeDialog({ po, onClose }: { po: PoDetail; onClose: () => void }) {
  const [lines, setLines] = useState(po.lines.map((l) => ({ line: l, qty: String(Number(l.qty)), need_date: l.need_date })));
  const [reason, setReason] = useState('');
  const changes = lines.map((l) => {
    const change: { line: number; qty?: string; need_date?: string } = { line: l.line.line_no };
    if (isNumber(l.qty) && Number(l.qty) !== Number(l.line.qty)) change.qty = l.qty;
    if (l.need_date && l.need_date !== l.line.need_date) change.need_date = l.need_date;
    return change;
  }).filter((c) => c.qty !== undefined || c.need_date !== undefined);
  const belowReceived = lines.filter((l) => isNumber(l.qty) && Number(l.qty) < Number(l.line.received_qty));
  const invalid = lines.some((l) => !isPositive(l.qty)) || belowReceived.length > 0;
  const send = useCommand(() => api.post<{ number: string }>(`/purchase-orders/${encodeURIComponent(po.number)}/change-requests`,
    { lines: changes, reason: reason.trim() }), {
    success: (r) => `Change request ${r.number} sent to the buyer`, onSuccess: onClose,
  });
  const update = (i: number, patch: { qty?: string; need_date?: string }) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <Dialog open title={`Request change to ${po.number} v${po.version}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-600">Change quantity or delivery date only; price changes go through the contract. The buyer accepts or rejects the request,
          and an accepted request creates a new PO version for you to confirm.</p>
        {lines.map((l, i) => (
          <div key={l.line.id} className="grid gap-3 rounded-lg border border-slate-200 p-3 md:grid-cols-3">
            <div className="text-sm">
              <p className="font-medium">Line {l.line.line_no}</p>
              <p className="text-slate-600">{l.line.description}</p>
              <p className="text-xs text-slate-500">Ordered {qty(l.line.qty, l.line.uom)} by {date(l.line.need_date)} · received {qty(l.line.received_qty)}</p>
            </div>
            <Field label="New quantity">{(id) => <Input id={id} value={l.qty} onChange={(e) => update(i, { qty: e.target.value })} />}</Field>
            <Field label="New delivery date">{(id) => <Input id={id} type="date" value={l.need_date} onChange={(e) => update(i, { need_date: e.target.value })} />}</Field>
          </div>
        ))}
        {belowReceived.length > 0 && (
          <p role="alert" className="text-sm text-red-700">Line {belowReceived.map((l) => l.line.line_no).join(', ')}: quantity cannot be below what was already received.</p>
        )}
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Furnace relining on cell 2; can ship on 20 Mar instead of 18 Mar" />}</Field>
        <ProblemBox error={send.error} />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!changes.length || invalid || !reason.trim()} busy={send.isPending} onClick={() => send.mutate()}>Send change request</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- corrective actions (CAPA, SLM-03)
type CapaAction = { action: string; due: string };
export type Capa = { id: string; number: string; source_type: string; source_ref: string; finding: string; root_cause: string | null;
  actions: CapaAction[] | null; due_date: string; status: string; closed_at: string | null; created_at: string };

export function CapaResponseDialog({ capa, onClose }: { capa: Capa; onClose: () => void }) {
  const [rootCause, setRootCause] = useState(capa.root_cause ?? '');
  const [actions, setActions] = useState<CapaAction[]>(capa.actions?.length ? capa.actions : [{ action: '', due: capa.due_date }]);
  const filled = actions.filter((a) => a.action.trim());
  const invalid = !rootCause.trim() || !filled.length || filled.some((a) => !a.due);
  const send = useCommand(() => api.post(`/capas/${encodeURIComponent(capa.number)}/response`, {
    root_cause: rootCause.trim(), actions: filled.map((a) => ({ action: a.action.trim(), due: a.due })),
  }), { success: `${capa.number} response sent to Axion quality`, onSuccess: onClose });
  const update = (i: number, patch: Partial<CapaAction>) => setActions((as) => as.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  return (
    <Dialog open title={`Respond to ${capa.number}`} onClose={onClose}>
      <div className="space-y-3">
        <div className="rounded-lg bg-slate-50 p-3 text-sm">
          <p className="font-medium">Finding</p>
          <p className="text-slate-700">{capa.finding}</p>
          <p className="mt-1 text-xs text-slate-500">Source {label(capa.source_type)} {capa.source_ref} · response due {date(capa.due_date)}</p>
        </div>
        <Field label="Root cause (required)" hint="8D D4: the verified cause, not the symptom.">
          {(id) => <Textarea id={id} value={rootCause} onChange={(e) => setRootCause(e.target.value)} placeholder="e.g. Porosity from die temperature drift on cell 4" />}
        </Field>
        <div>
          <p className="text-xs font-medium text-slate-700">Corrective actions (at least one)</p>
          <div className="mt-1 space-y-2">
            {actions.map((a, i) => (
              <div key={i} className="grid gap-2 md:grid-cols-[1fr_160px_auto] md:items-end">
                <Field label={`Action ${i + 1}`}>{(id) => <Input id={id} value={a.action} onChange={(e) => update(i, { action: e.target.value })} placeholder="e.g. Install die thermocouple alarms" />}</Field>
                <Field label="Due">{(id) => <Input id={id} type="date" value={a.due} onChange={(e) => update(i, { due: e.target.value })} />}</Field>
                {actions.length > 1 ? <Button variant="ghost" onClick={() => setActions((as) => as.filter((_, j) => j !== i))}>Remove</Button> : <span />}
              </div>
            ))}
          </div>
          <Button className="mt-2" onClick={() => setActions((as) => [...as, { action: '', due: capa.due_date }])}>Add action</Button>
        </div>
        <p className="text-xs text-slate-500">Axion quality verifies effectiveness; an ineffective response reopens the CAPA.</p>
        <ProblemBox error={send.error} />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={invalid} busy={send.isPending} onClick={() => send.mutate()}>Send response</Button>
      </div>
    </Dialog>
  );
}

export function CapaPanel() {
  const { data, isLoading, error } = useApi<Capa[]>('/capas');
  const [open, setOpen] = useState<Capa | null>(null);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  return (
    <Card title="Corrective actions (CAPA)">
      <p className="mb-3 text-sm text-slate-600">Quality findings raised against your deliveries. Respond with the root cause and dated corrective actions; you can update a response until Axion verifies it.</p>
      {!data?.length ? <Empty title="No corrective actions requested" hint="CAPAs appear here when an inspection lot or audit finds a defect." /> : (
        <ul className="divide-y divide-slate-100">
          {data.map((c) => {
            const overdue = c.status === 'OPEN' && c.due_date < today();
            return (
              <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono font-semibold">{c.number}</span><StatusChip status={overdue ? 'OVERDUE' : c.status} />
                    <span className="text-xs text-slate-500">raised {dateTime(c.created_at)} · due {date(c.due_date)}</span>
                  </p>
                  <p className="mt-1 text-sm text-slate-800">{c.finding}</p>
                  {c.root_cause && <p className="mt-1 text-sm text-slate-600"><span className="font-medium">Root cause:</span> {c.root_cause}</p>}
                  {!!c.actions?.length && (
                    <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">{c.actions.map((a, i) => <li key={i}>{a.action} — by {date(a.due)}</li>)}</ul>
                  )}
                </div>
                {['OPEN', 'RESPONDED'].includes(c.status) && (
                  <Button variant={c.status === 'OPEN' ? 'primary' : 'secondary'} onClick={() => setOpen(c)}>{c.status === 'OPEN' ? 'Respond' : 'Update response'}</Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {open && <CapaResponseDialog capa={open} onClose={() => setOpen(null)} />}
    </Card>
  );
}
