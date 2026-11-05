'use client';

// The supplier's sealed bid (RFQ / RFP): per-line price terms, currency and incoterm, offer validity, replacement before the close and withdrawal.
import { useState } from 'react';
import { Button, Dialog, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { isNumber, isPositive } from '../invoices/_components';

type EventLine = { id: string; line_no: number; description: string; plant: string; annual_qty: string; monthly_qty: string; uom: string; lot_code?: string | null };
type SourcingEvent = { id: string; number: string; type: string; title: string; category: string; status: string; round: number; close_at: string; open_at?: string | null;
  clarification_close_at?: string | null; reference_date?: string | null; published_at: string | null; currency: string; lines: EventLine[]; criteria: { code: string; name: string; weight: number }[];
  bids: { supplier: string; round: number; status: string; submittedAt: string; hash: string }[] };
type BidDraft = {
  unit_price: string; freight: string; duty: string; packaging: string; payment_terms_days: string; lead_time_days: string; capacity_per_month: string;
  currency: string; incoterm: string; origin: string; moq: string; price_uom: string; uom_factor: string; tax_included: boolean; tax_rate_pct: string; hs_code: string;
};
type Receipt = { round: number; status: string; hash: string; submittedAt: string };

const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'JPY', 'CNY', 'AED', 'SGD'];
const INCOTERMS = ['EXW', 'FCA', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP'];
const blank = (v: string) => v.trim() === '';
const optNumber = (v: string) => blank(v) || isNumber(v);

function lineProblems(d: BidDraft): string[] {
  const out: string[] = [];
  if (!isPositive(d.unit_price)) out.push('unit price');
  for (const [k, name] of [['freight', 'freight'], ['duty', 'duty'], ['packaging', 'packaging'], ['moq', 'MOQ'], ['capacity_per_month', 'capacity']] as const) if (!optNumber(d[k])) out.push(name);
  if (!isNumber(d.payment_terms_days)) out.push('payment terms');
  if (!isNumber(d.lead_time_days)) out.push('lead time');
  if (!/^[A-Za-z]{3}$/.test(d.currency.trim())) out.push('currency (three letters)');
  if (!blank(d.uom_factor) && !(isNumber(d.uom_factor) && Number(d.uom_factor) > 0)) out.push('unit-of-measure factor');
  if (!blank(d.tax_rate_pct) && !(isNumber(d.tax_rate_pct) && Number(d.tax_rate_pct) >= 0 && Number(d.tax_rate_pct) <= 50)) out.push('tax rate (0-50 %)');
  return out;
}

export function BidDialog({ number, onClose }: { number: string; onClose: () => void }) {
  const path = `/sourcing/events/${encodeURIComponent(number)}`;
  const { data: event, isLoading, error } = useApi<SourcingEvent>(path);
  const [drafts, setDrafts] = useState<Record<number, BidDraft>>({});
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [withdrawn, setWithdrawn] = useState<string | null>(null);
  const [prefilled, setPrefilled] = useState(false);
  const [skipped, setSkipped] = useState<Record<number, boolean>>({});
  const [lotTerms, setLotTerms] = useState<Record<string, { discount: string; allOrNothing: boolean }>>({});
  const [validUntil, setValidUntil] = useState('');
  const [reason, setReason] = useState('');
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  if (event && !prefilled) {
    setPrefilled(true);
    setDrafts(Object.fromEntries(event.lines.map((l) => [l.line_no, {
      unit_price: '', freight: '', duty: '', packaging: '', payment_terms_days: '60', lead_time_days: '', capacity_per_month: String(Number(l.monthly_qty)),
      currency: 'INR', incoterm: '', origin: '', moq: '', price_uom: '', uom_factor: '', tax_included: false, tax_rate_pct: '', hs_code: '',
    }])));
    setValidUntil(new Date(new Date(event.close_at).getTime() + 45 * 864e5).toISOString().slice(0, 10));
  }
  const open = !!event && event.status === 'OPEN' && new Date(event.close_at) > new Date();
  const myRoundBid = event?.bids.find((b) => b.round === event.round);
  const myLive = myRoundBid && myRoundBid.status !== 'WITHDRAWN' && !withdrawn ? myRoundBid : null;
  const multi = (event?.lines.length ?? 0) > 1;
  const entries = event?.lines.map((l) => ({ line: l, d: drafts[l.line_no] })).filter((e) => e.d && !skipped[e.line.line_no]) ?? [];
  const lotCodes = Array.from(new Set((event?.lines ?? []).map((l) => l.lot_code).filter((c): c is string => !!c)));
  // lot terms (a discount for the whole lot, all-or-nothing) need a price for every line of the lot
  const lotProblems = lotCodes.filter((code) => {
    const t = lotTerms[code];
    const wants = !!t && (Number(t.discount) > 0 || t.allOrNothing);
    return wants && (event?.lines ?? []).some((l) => l.lot_code === code && skipped[l.line_no]);
  });
  const lotDiscountBad = lotCodes.some((code) => lotTerms[code]?.discount && !(Number(lotTerms[code].discount) >= 0 && Number(lotTerms[code].discount) < 100));
  const validBad = !blank(validUntil) && !!event && new Date(`${validUntil}T00:00:00`) <= new Date(event.close_at);
  const invalid = lotProblems.length > 0 || lotDiscountBad || validBad || !entries.length || entries.some(({ d }) => lineProblems(d).length > 0);
  const submit = useCommand(() => api.post<Receipt>(`${path}/bids`, {
    lines: entries.map(({ line, d }) => ({
      line: line.line_no, unit_price: d.unit_price,
      ...(blank(d.freight) ? {} : { freight: d.freight }), ...(blank(d.duty) ? {} : { duty: d.duty }), ...(blank(d.packaging) ? {} : { packaging: d.packaging }),
      payment_terms_days: Number(d.payment_terms_days), lead_time_days: Number(d.lead_time_days),
      ...(blank(d.capacity_per_month) ? {} : { capacity_per_month: d.capacity_per_month }),
      currency: d.currency.trim().toUpperCase(),
      ...(blank(d.incoterm) ? {} : { incoterm: d.incoterm.trim().toUpperCase() }), ...(blank(d.origin) ? {} : { origin: d.origin }),
      ...(blank(d.moq) ? {} : { moq: d.moq }), ...(blank(d.price_uom) ? {} : { price_uom: d.price_uom.trim().toUpperCase() }), ...(blank(d.uom_factor) ? {} : { uom_factor: d.uom_factor }),
      tax_included: d.tax_included, ...(blank(d.tax_rate_pct) ? {} : { tax_rate_pct: d.tax_rate_pct }), ...(blank(d.hs_code) ? {} : { hs_code: d.hs_code.trim() }),
    })),
    lots: lotCodes.filter((code) => lotTerms[code] && (Number(lotTerms[code].discount) > 0 || lotTerms[code].allOrNothing))
      .map((code) => ({ lot: code, discount_pct: lotTerms[code].discount || '0', all_or_nothing: lotTerms[code].allOrNothing })),
    ...(blank(validUntil) ? {} : { valid_until: validUntil }),
  }), { success: 'Sealed bid submitted', onSuccess: (r) => { setReceipt(r); setWithdrawn(null); } });
  const withdraw = useCommand(() => api.post<{ withdrawnAt: string }>(`${path}/bids/withdraw`, { reason: reason.trim() }), {
    success: 'Bid withdrawn: its content was destroyed unread; you can bid again before the close', onSuccess: (r) => { setWithdrawn(r.withdrawnAt); setReceipt(null); setConfirmWithdraw(false); setReason(''); },
  });
  const update = (line: number, patch: Partial<BidDraft>) => setDrafts((ds) => ({ ...ds, [line]: { ...ds[line], ...patch } }));

  return (
    <Dialog open title={`${number} · ${open ? 'Submit sealed bid' : 'Event details'}`} onClose={onClose} wide>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : event && (
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium">{event.title}</p>
            <p className="text-xs text-slate-600">{event.type} · {event.category} · round {event.round} · closes {dateTime(event.close_at)}{event.reference_date ? ` · prices convert at the rates of ${date(event.reference_date)}` : ''}</p>
            <div className="mt-1"><StatusChip status={event.status} /></div>
          </div>
          <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 text-sm text-slate-800">
            Bids are encrypted when you submit them and stay sealed until the event closes at <span className="font-semibold">{dateTime(event.close_at)}</span> —
            nobody at the buyer can read prices before the opening. You can resubmit any time before close; your new bid replaces the previous one for this round, or withdraw it.
          </div>
          {event.criteria.length > 0 && (
            <p className="text-xs text-slate-600">Evaluation: {event.criteria.map((c) => `${c.name} ${c.weight}%`).join(' · ')}</p>
          )}
          {(receipt || myLive) && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" role="status">
              {receipt ? 'Bid received' : 'Your bid on file'} for round {(receipt ?? myLive)!.round} · {label((receipt ?? myLive)!.status)} ·
              {' '}{dateTime(receipt?.submittedAt ?? myLive!.submittedAt)}
              <p className="mt-1 break-all font-mono text-[11px]">SHA-256 {receipt?.hash ?? myLive!.hash}</p>
            </div>
          )}
          {(withdrawn || myRoundBid?.status === 'WITHDRAWN') && !receipt && (
            <p className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700" role="status">Your bid for this round is withdrawn. It was never opened. {open ? 'You may submit a new bid below.' : ''}</p>
          )}
          {event.bids.filter((b) => b.round !== event.round).map((b) => (
            <p key={b.round} className="text-xs text-slate-500">Round {b.round}: {label(b.status)} · {dateTime(b.submittedAt)}</p>
          ))}
          {open ? (
            <>
              {multi && <p className="text-sm text-slate-700">This event has {event.lines.length} lines. Price each line you want to bid; you may leave a line out unless the buyer requires a price for every line (the server tells you).</p>}
              <p className="text-xs text-slate-600">Freight, duty and packaging: enter them only if you quote them. Left empty, the buyer&apos;s TCO rule estimates freight from your incoterm and, for an import, duty from the HS code.</p>
              {event.lines.map((l) => drafts[l.line_no] && (
                <fieldset key={l.id} className={`rounded-lg border p-3 ${skipped[l.line_no] ? 'border-slate-200 bg-slate-50' : 'border-slate-200'}`}>
                  <legend className="px-1 text-sm font-medium">Line {l.line_no} · {l.description}{l.lot_code && <span className="ml-2 rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-violet-800">lot {l.lot_code}</span>}</legend>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-slate-500">{qty(l.annual_qty, l.uom)} per year · {qty(l.monthly_qty, l.uom)} per month · plant {l.plant}</p>
                    {multi && (
                      <label className="flex items-center gap-2 text-xs text-slate-700">
                        <input type="checkbox" className="h-4 w-4" checked={!skipped[l.line_no]} onChange={(e) => setSkipped((s) => ({ ...s, [l.line_no]: !e.target.checked }))} /> Bid on this line
                      </label>
                    )}
                  </div>
                  {!skipped[l.line_no] && (() => {
                    const d = drafts[l.line_no];
                    const probs = lineProblems(d);
                    return (
                      <>
                        <div className="mt-2 grid gap-3 md:grid-cols-4">
                          <Field label="Unit price" required>{(id) => <Input id={id} inputMode="decimal" value={d.unit_price} onChange={(e) => update(l.line_no, { unit_price: e.target.value })} />}</Field>
                          <Field label="Currency" hint="Converted at the event's pricing date">{(id) => <Input id={id} list={`cur-${l.line_no}`} maxLength={3} value={d.currency} onChange={(e) => update(l.line_no, { currency: e.target.value.toUpperCase() })} />}</Field>
                          <Field label="Incoterm">{(id) => <Input id={id} list="bid-incoterms" maxLength={10} value={d.incoterm} onChange={(e) => update(l.line_no, { incoterm: e.target.value.toUpperCase() })} />}</Field>
                          <Field label="Origin">{(id) => <Select id={id} value={d.origin} onChange={(e) => update(l.line_no, { origin: e.target.value })}
                            options={[{ value: '', label: 'From my supplier country' }, { value: 'DOMESTIC', label: 'Domestic' }, { value: 'IMPORT', label: 'Import' }]} />}</Field>
                          <Field label="Freight / unit" hint="Empty: not quoted">{(id) => <Input id={id} inputMode="decimal" value={d.freight} onChange={(e) => update(l.line_no, { freight: e.target.value })} />}</Field>
                          <Field label="Duty / unit" hint="Empty: not quoted">{(id) => <Input id={id} inputMode="decimal" value={d.duty} onChange={(e) => update(l.line_no, { duty: e.target.value })} />}</Field>
                          <Field label="Packaging / unit" hint="Empty: not quoted">{(id) => <Input id={id} inputMode="decimal" value={d.packaging} onChange={(e) => update(l.line_no, { packaging: e.target.value })} />}</Field>
                          <Field label="HS code" hint="Needed for an import's duty">{(id) => <Input id={id} maxLength={10} value={d.hs_code} onChange={(e) => update(l.line_no, { hs_code: e.target.value })} />}</Field>
                          <Field label="Payment terms (days)" required>{(id) => <Input id={id} inputMode="numeric" value={d.payment_terms_days} onChange={(e) => update(l.line_no, { payment_terms_days: e.target.value })} />}</Field>
                          <Field label="Lead time (days)" required>{(id) => <Input id={id} inputMode="numeric" value={d.lead_time_days} onChange={(e) => update(l.line_no, { lead_time_days: e.target.value })} />}</Field>
                          <Field label={`Capacity / month (${l.uom})`}>{(id) => <Input id={id} inputMode="decimal" value={d.capacity_per_month} onChange={(e) => update(l.line_no, { capacity_per_month: e.target.value })} />}</Field>
                          <Field label={`Minimum order qty / month (${l.uom})`}>{(id) => <Input id={id} inputMode="decimal" value={d.moq} onChange={(e) => update(l.line_no, { moq: e.target.value })} />}</Field>
                          <Field label="Price is per (unit of measure)" hint="If not the buyer's unit, e.g. KG">{(id) => <Input id={id} maxLength={5} value={d.price_uom} onChange={(e) => update(l.line_no, { price_uom: e.target.value.toUpperCase() })} />}</Field>
                          <Field label={`${l.uom} in one priced unit`} hint="UoM factor, empty = 1">{(id) => <Input id={id} inputMode="decimal" value={d.uom_factor} onChange={(e) => update(l.line_no, { uom_factor: e.target.value })} />}</Field>
                          <Field label="Tax rate (%)">{(id) => <Input id={id} inputMode="decimal" value={d.tax_rate_pct} onChange={(e) => update(l.line_no, { tax_rate_pct: e.target.value })} />}</Field>
                          <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={d.tax_included} onChange={(e) => update(l.line_no, { tax_included: e.target.checked })} /> My price includes tax</label>
                        </div>
                        {probs.length > 0 && <p role="alert" className="mt-1 text-xs text-red-700">Check: {probs.join(', ')}.</p>}
                      </>
                    );
                  })()}
                  <datalist id={`cur-${l.line_no}`}>{CURRENCIES.map((c) => <option key={c} value={c} />)}</datalist>
                </fieldset>
              ))}
              <datalist id="bid-incoterms">{INCOTERMS.map((c) => <option key={c} value={c} />)}</datalist>
              {lotCodes.map((code) => (
                <div key={code} className="rounded-lg border border-violet-200 bg-violet-50/40 p-3">
                  <p className="text-sm font-medium">Lot {code} · bundle terms (optional)</p>
                  <p className="text-xs text-slate-600">Lines {event.lines.filter((l) => l.lot_code === code).map((l) => l.line_no).join(', ')}. A discount applies only if you are awarded the whole lot.
                    All-or-nothing means you accept the lot only as a whole. Both need a price on every line of the lot.</p>
                  <div className="mt-2 grid items-end gap-3 md:grid-cols-3">
                    <Field label="Lot discount (%)">{(id) => <Input id={id} inputMode="decimal" value={lotTerms[code]?.discount ?? ''}
                      onChange={(e) => setLotTerms((t) => ({ ...t, [code]: { discount: e.target.value, allOrNothing: t[code]?.allOrNothing ?? false } }))} />}</Field>
                    <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" className="h-4 w-4" checked={lotTerms[code]?.allOrNothing ?? false}
                      onChange={(e) => setLotTerms((t) => ({ ...t, [code]: { discount: t[code]?.discount ?? '', allOrNothing: e.target.checked } }))} /> All or nothing</label>
                  </div>
                  {lotProblems.includes(code) && <p role="alert" className="mt-1 text-sm text-red-700">Bid every line of lot {code} to offer these terms.</p>}
                </div>
              ))}
              <div className="grid gap-3 md:grid-cols-3">
                <Field label="Offer valid until" hint="Must be after the close; the buyer cannot award an expired offer" error={validBad ? 'The offer must stay valid after the event closes.' : undefined}>{(id, d) => <Input id={id} aria-describedby={d} type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />}</Field>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <div>{myLive && <Button variant="danger" onClick={() => setConfirmWithdraw((v) => !v)} aria-expanded={confirmWithdraw}>Withdraw my bid</Button>}</div>
                <div className="flex gap-2">
                  <Button onClick={onClose}>Close</Button>
                  <Button variant="primary" disabled={invalid} busy={submit.isPending} onClick={() => submit.mutate()}>
                    {myLive || receipt ? 'Replace sealed bid' : 'Submit sealed bid'}
                  </Button>
                </div>
              </div>
              {confirmWithdraw && (
                <div className="space-y-2 rounded-lg border border-red-200 bg-red-50/40 p-3">
                  <p className="text-sm text-slate-800">Withdrawing destroys your sealed bid; it is never opened. You may bid again until the close.</p>
                  <Field label="Reason (shown to the buyer)" required>{(id) => <Textarea id={id} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />}</Field>
                  <div className="flex justify-end gap-2">
                    <Button onClick={() => setConfirmWithdraw(false)}>Keep my bid</Button>
                    <Button variant="danger" disabled={reason.trim().length < 3} busy={withdraw.isPending} onClick={() => withdraw.mutate()}>Withdraw bid</Button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <ul className="text-sm text-slate-700">{event.lines.map((l) => <li key={l.id}>Line {l.line_no} · {l.description} · {qty(l.annual_qty, l.uom)} per year</li>)}</ul>
              <p className="text-sm text-slate-600">
                {event.status === 'PUBLISHED' ? `Bidding opens ${event.open_at ? `at ${dateTime(event.open_at)}` : 'once the event is opened by the buyer'}; you may ask questions${event.clarification_close_at ? ` until ${dateTime(event.clarification_close_at)}` : ''}.` : 'Bidding is closed for this event.'}
              </p>
              <div className="flex justify-end"><Button onClick={onClose}>Close</Button></div>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
