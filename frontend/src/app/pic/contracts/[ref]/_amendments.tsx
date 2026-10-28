'use client';

import Link from 'next/link';
import { Fragment, ReactNode, useEffect, useMemo, useState } from 'react';
import { Button, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- shapes (GET/POST /contracts/{ref}/amendments[/preview])
export type AmendKind = 'VARIATION' | 'EXTENSION' | 'TERMS' | 'TERMINATION';
export type ContractForAmendment = {
  number: string; status: string; version?: number; valid_from: string; valid_to: string; payment_terms: string; incoterms: string | null;
  over_tolerance_pct: string; under_tolerance_pct: string; price_tolerance_pct: string; target_value_minor: number;
  lines: { id: string; line_no: number; description: string; uom: string; target_qty: string; released_qty: string }[];
  priceValidity: { contract_line_id: string; valid_from: string; valid_to: string; unit_price_minor: number; published: boolean }[];
  clauses: { code: string; title: string; text: string; position: string }[];
};
type Person = { id: string; name?: string; email?: string } | null;
type AmendTask = { id: string; role: string; status: string; decision: string | null; comment: string | null; dueAt: string | null;
  completedBy: Person; completedAt: string | null };
type Snapshot = Record<string, unknown>;
export type Amendment = {
  id: string; number: string; contract: string; kind: AmendKind; status: string; reason: string; effective_from: string; from_version: number;
  to_version: number | null; changes: Record<string, unknown> & { valueDeltaMinor?: number; approvalChain?: string[]; band?: string; ruleSet?: string };
  snapshot: Snapshot; requestedBy?: Person; approvedBy?: Person; decided_at: string | null; created_at: string; tasks?: AmendTask[];
};
type Listing = {
  contract: string; status: string; version: number; terminatedAt: string | null; terminationReason: string | null;
  rule: { ref: string; thresholdMinor: number; noticeDays: number; above: string[]; below: string[]; termination: string[] };
  items: Amendment[];
};
type Plan = {
  kind: AmendKind; effectiveFrom: string; fromVersion: number; changes: Record<string, unknown>; before: Snapshot; after: Snapshot;
  valueDeltaMinor: number; band: string; approvalChain: string[]; thresholdMinor: number; ruleSet: string; noticeDays?: number;
  earliestWithoutCause?: string; openPurchaseOrders?: { number: string; status: string; totalMinor: number }[];
};

const PENDING = ['DRAFT', 'IN_APPROVAL', 'APPROVED'];
const KIND_LABEL: Record<AmendKind, string> = {
  VARIATION: 'Variation – price / quantity', EXTENSION: 'Extension – validity', TERMS: 'Terms – payment, incoterms, tolerances, clauses',
  TERMINATION: 'Termination',
};

export function todayIst() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
}

function addDays(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function addMonths(iso: string, months: number) {
  const [y, m, d] = iso.split('-').map(Number);
  const monthEnd = (yy: number, mm: number) => new Date(Date.UTC(yy, mm, 0)).getUTCDate();
  const total = m - 1 + months;
  const year = y + Math.floor(total / 12);
  const month = (total % 12) + 1;
  const day = d === monthEnd(y, m) ? monthEnd(year, month) : Math.min(d, monthEnd(year, month));
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function delta(minor: number | undefined) {
  if (minor === undefined || minor === null) return '–';
  const tone = minor > 0 ? 'text-amber-700' : minor < 0 ? 'text-emerald-700' : 'text-slate-600';
  return <span className={`tabular-nums ${tone}`}>{minor > 0 ? '+' : ''}{inr(minor)}</span>;
}

// ---------------------------------------------------------------- tab: list, approval state, version history
export function AmendmentsTab({ contract, canManage }: { contract: ContractForAmendment; canManage: boolean }) {
  const path = `/contracts/${encodeURIComponent(contract.number)}/amendments`;
  const { data, isLoading, error } = useApi<Listing>(path);
  const [open, setOpen] = useState<string | null>(null);
  const [withdrawing, setWithdrawing] = useState<Amendment | null>(null);
  const submit = useCommand((number: string) => api.post<Amendment>(`${path}/${encodeURIComponent(number)}/submit`),
    { success: (a) => `${a.number} submitted: ${(a.changes.approvalChain ?? []).map(label).join(' → ')}` });
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  const effective = data.items.filter((a) => a.status === 'EFFECTIVE').sort((a, b) => (a.to_version ?? 0) - (b.to_version ?? 0));
  return (
    <div className="space-y-5">
      <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
        <p>
          Current version <span className="font-semibold">v{data.version}</span>. Approval route ({data.rule.ref}): value change ≥ {inr(data.rule.thresholdMinor)} →{' '}
          {data.rule.above.map(label).join(' → ')}; below → {data.rule.below.map(label).join(' → ')}; termination → {data.rule.termination.map(label).join(' → ')}.
          The requester never approves their own amendment. Termination without cause needs {data.rule.noticeDays} days&apos; notice.
        </p>
        {data.terminatedAt && <p className="mt-1 font-medium text-red-800">Terminated {dateTime(data.terminatedAt)}: {data.terminationReason}</p>}
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Version history</h3>
        <ol className="relative ml-3 border-l-2 border-slate-200">
          <li className="mb-3 ml-5">
            <span className="absolute -left-[9px] mt-1 h-4 w-4 rounded-full bg-emerald-500 ring-4 ring-white" aria-hidden />
            <p className="text-sm"><span className="font-mono text-xs text-slate-500">v1</span> <span className="font-medium">Signed and activated</span></p>
          </li>
          {effective.map((a) => (
            <li key={a.id} className="mb-3 ml-5">
              <span className={`absolute -left-[9px] mt-1 h-4 w-4 rounded-full ring-4 ring-white ${a.kind === 'TERMINATION' ? 'bg-red-500' : 'bg-emerald-500'}`} aria-hidden />
              <p className="text-sm">
                <span className="font-mono text-xs text-slate-500">v{a.from_version} → v{a.to_version}</span>{' '}
                <span className="font-medium">{a.number} · {label(a.kind)}</span> <span className="text-slate-500">from {date(a.effective_from)}</span>
              </p>
              <p className="text-sm text-slate-700">{a.reason}</p>
              <p className="text-xs text-slate-500">approved by {a.approvedBy?.name ?? '–'} · {dateTime(a.decided_at)}</p>
            </li>
          ))}
        </ol>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Amendments</h3>
        {!data.items.length ? <Empty title="No amendments yet" hint={canManage ? 'Use “Amend” or “Terminate” above to raise one.' : undefined} /> : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Amendment</th><th className="px-3 py-2">Kind</th><th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Effective</th><th className="px-3 py-2 text-right">Value change</th><th className="px-3 py-2">Approval</th><th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {data.items.map((a) => (
                  <Fragment key={a.id}>
                    <tr>
                      <td className="px-3 py-2 align-top">
                        <button className="font-medium text-[#1A56DB] hover:underline" onClick={() => setOpen(open === a.id ? null : a.id)} aria-expanded={open === a.id}>{a.number}</button>
                        <p className="text-xs text-slate-500">v{a.from_version}{a.to_version ? ` → v${a.to_version}` : ''} · by {a.requestedBy?.name ?? '–'}</p>
                      </td>
                      <td className="px-3 py-2 align-top">{label(a.kind)}</td>
                      <td className="px-3 py-2 align-top"><StatusChip status={a.status} /></td>
                      <td className="px-3 py-2 align-top">{date(a.effective_from)}</td>
                      <td className="px-3 py-2 text-right align-top">{delta(a.changes.valueDeltaMinor)}</td>
                      <td className="px-3 py-2 align-top"><ApprovalState amendment={a} /></td>
                      <td className="px-3 py-2 text-right align-top">
                        {canManage && a.status === 'DRAFT' && <Button variant="primary" busy={submit.isPending} onClick={() => submit.mutate(a.number)}>Submit</Button>}
                        {canManage && PENDING.includes(a.status) && <Button variant="ghost" onClick={() => setWithdrawing(a)}>Withdraw</Button>}
                      </td>
                    </tr>
                    {open === a.id && (
                      <tr><td colSpan={7} className="bg-slate-50/60 px-4 py-3"><AmendmentDetail amendment={a} /></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {withdrawing && <WithdrawDialog path={path} amendment={withdrawing} onClose={() => setWithdrawing(null)} />}
    </div>
  );
}

function ApprovalState({ amendment }: { amendment: Amendment }) {
  const chain = amendment.changes.approvalChain ?? [];
  const tasks = amendment.tasks ?? [];
  if (!chain.length) return <span className="text-slate-500">–</span>;
  return (
    <ol className="flex flex-wrap items-center gap-1 text-xs">
      {chain.map((role, i) => {
        const t = tasks.filter((x) => x.role === role).slice(-1)[0];
        const state = t ? (t.status === 'COMPLETED' ? t.decision ?? 'DONE' : t.status) : amendment.status === 'DRAFT' ? 'not started' : 'waiting';
        const tone = state === 'APPROVE' ? 'text-emerald-700' : state === 'REJECT' || state === 'RETURN' ? 'text-red-700' : state === 'OPEN' ? 'text-amber-700' : 'text-slate-500';
        return (
          <li key={`${role}-${i}`} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden className="text-slate-300">→</span>}
            <span className={tone} title={t?.comment ?? undefined}>{label(role)}: {state === 'APPROVE' ? `approved${t?.completedBy?.name ? ` (${t.completedBy.name})` : ''}` : label(state)}</span>
          </li>
        );
      })}
    </ol>
  );
}

function AmendmentDetail({ amendment }: { amendment: Amendment }) {
  const before = amendment.snapshot ?? {};
  const after = amendment.changes;
  return (
    <div className="space-y-2 text-sm">
      <p className="text-slate-700"><span className="font-medium">Reason:</span> {amendment.reason}</p>
      <ChangeTable kind={amendment.kind} before={before} after={after} />
      <p className="font-mono text-[11px] text-slate-400">{amendment.changes.ruleSet} · band {amendment.changes.band}</p>
    </div>
  );
}

type LineSnap = { line: number; description?: string; unitPriceMinor?: number; targetQty?: string; releasedQty?: string; valueDeltaMinor?: number };

/** Before → after view shared by the stored amendment and the live preview. */
function ChangeTable({ kind, before, after }: { kind: AmendKind; before: Snapshot; after: Snapshot }) {
  const rows: [string, ReactNode, ReactNode][] = [];
  if (kind === 'VARIATION') {
    const b = (before.lines as LineSnap[] | undefined) ?? [];
    const a = (after.lines as LineSnap[] | undefined) ?? [];
    for (const line of a) {
      const old = b.find((x) => x.line === line.line);
      if (line.unitPriceMinor !== undefined) rows.push([`Line ${line.line} unit price`, inr(old?.unitPriceMinor), inr(line.unitPriceMinor)]);
      if (line.targetQty !== undefined) rows.push([`Line ${line.line} target qty`, qty(old?.targetQty), qty(line.targetQty)]);
    }
  } else if (kind === 'EXTENSION') {
    rows.push(['Valid to', date(before.validTo as string), date(after.validTo as string)]);
  } else if (kind === 'TERMS') {
    if (after.paymentTerms !== undefined) rows.push(['Payment terms', String(before.paymentTerms ?? '–'), String(after.paymentTerms)]);
    if (after.incoterms !== undefined) rows.push(['Incoterms', String(before.incoterms ?? '–'), String(after.incoterms)]);
    const tb = (before.tolerances as Record<string, string> | undefined) ?? {};
    for (const [k, v] of Object.entries((after.tolerances as Record<string, string> | undefined) ?? {})) rows.push([`Tolerance ${label(k)}`, `${tb[k] ?? '–'}%`, `${v}%`]);
    const cb = (before.clauses as { code: string; text: string | null }[] | undefined) ?? [];
    for (const c of (after.clauses as { code: string; text: string; position: string }[] | undefined) ?? []) {
      rows.push([`Clause ${c.code} (${label(c.position)})`, <span key="b" className="text-slate-500">{cb.find((x) => x.code === c.code)?.text ?? 'new clause'}</span>, c.text]);
    }
  } else {
    rows.push(['Status', String(before.status ?? '–'), 'TERMINATED']);
    if (after.lastDayInForce) rows.push(['Last day in force', date(before.validTo as string), date(after.lastDayInForce as string)]);
    if (after.forCause !== undefined) rows.push(['For cause', '', after.forCause ? 'Yes' : 'No (notice period applies)']);
  }
  if (!rows.length) return <p className="text-sm text-slate-500">No changes recorded.</p>;
  return (
    <table className="min-w-full text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="py-1 pr-3">Field</th><th className="py-1 pr-3">Before</th><th className="py-1">After</th></tr></thead>
      <tbody className="divide-y divide-slate-100">
        {rows.map(([f, b, a]) => (
          <tr key={f}><td className="py-1 pr-3 text-slate-600">{f}</td><td className="py-1 pr-3 tabular-nums">{b}</td><td className="py-1 font-semibold tabular-nums">{a}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function WithdrawDialog({ path, amendment, onClose }: { path: string; amendment: Amendment; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const withdraw = useCommand(() => api.post(`${path}/${encodeURIComponent(amendment.number)}/withdraw`, { reason: reason.trim() }),
    { success: `${amendment.number} withdrawn`, onSuccess: onClose });
  return (
    <Dialog open title={`Withdraw ${amendment.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Open approval tasks are cancelled; a scheduled amendment will not take effect.</p>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={reason.trim().length < 3} busy={withdraw.isPending} onClick={() => withdraw.mutate()}>Withdraw</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- create dialog with live preview
type LineDraft = { price: string; qty: string };

function currentPrice(contract: ContractForAmendment, lineId: string, on: string) {
  const periods = contract.priceValidity.filter((p) => p.contract_line_id === lineId && p.published && p.valid_from <= on && p.valid_to >= on)
    .sort((a, b) => b.valid_from.localeCompare(a.valid_from));
  return periods[0]?.unit_price_minor ?? null;
}

export function AmendmentDialog({ contract, initialKind, noticeDays, onClose }: {
  contract: ContractForAmendment; initialKind: AmendKind; noticeDays?: number; onClose: () => void;
}) {
  const terminating = initialKind === 'TERMINATION';
  const [kind, setKind] = useState<AmendKind>(initialKind);
  const [effective, setEffective] = useState(() => (terminating ? addDays(todayIst(), noticeDays ?? 90) : todayIst()));
  const [reason, setReason] = useState('');
  const [lines, setLines] = useState<Record<number, LineDraft>>({});
  const [validTo, setValidTo] = useState(() => addMonths(contract.valid_to, 12));
  const [terms, setTerms] = useState({ paymentTerms: contract.payment_terms, incoterms: contract.incoterms ?? '', over: contract.over_tolerance_pct,
    under: contract.under_tolerance_pct, price: contract.price_tolerance_pct });
  const [clause, setClause] = useState<{ code: string; text: string }>({ code: '', text: '' });
  const [forCause, setForCause] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState<ApiError | null>(null);
  const [planning, setPlanning] = useState(false);
  const priceOn = effective > contract.valid_from ? effective : contract.valid_from;

  const changes = useMemo(() => {
    if (kind === 'VARIATION') {
      return { lines: contract.lines.flatMap((l) => {
        const d = lines[l.line_no];
        if (!d || (!d.price && !d.qty)) return [];
        return [{ line: l.line_no, ...(d.price ? { unitPriceMinor: rupeesToMinor(d.price) } : {}), ...(d.qty ? { targetQty: d.qty } : {}) }];
      }) };
    }
    if (kind === 'EXTENSION') return { validTo };
    if (kind === 'TERMS') {
      const out: Record<string, unknown> = {};
      if (terms.paymentTerms && terms.paymentTerms !== contract.payment_terms) out.paymentTerms = terms.paymentTerms;
      if (terms.incoterms && terms.incoterms !== (contract.incoterms ?? '')) out.incoterms = terms.incoterms;
      const tol: Record<string, string> = {};
      if (terms.over !== contract.over_tolerance_pct) tol.over_pct = terms.over;
      if (terms.under !== contract.under_tolerance_pct) tol.under_pct = terms.under;
      if (terms.price !== contract.price_tolerance_pct) tol.price_pct = terms.price;
      if (Object.keys(tol).length) out.tolerances = tol;
      if (clause.code && clause.text.trim()) out.clauses = [{ code: clause.code, text: clause.text.trim() }];
      return out;
    }
    return { forCause };
  }, [kind, lines, validTo, terms, clause, forCause, contract]);
  const payloadKey = JSON.stringify({ kind, changes, effective });

  // Live preview: the server validates the change set and returns the value delta and approval route (debounced).
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      setPlanning(true);
      api.post<Plan>(`/contracts/${encodeURIComponent(contract.number)}/amendments/preview`, { kind, changes, effective_from: effective || undefined },
        { idempotencyKey: false })
        .then((r) => { if (!cancelled) { setPlan(r); setPlanError(null); } })
        .catch((e: ApiError) => { if (!cancelled) { setPlan(null); setPlanError(e); } })
        .finally(() => { if (!cancelled) setPlanning(false); });
    }, 400);
    return () => { cancelled = true; clearTimeout(timer); };
    // payloadKey captures kind, changes and effective date.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payloadKey, contract.number]);

  const create = useCommand(() => api.post<Amendment>(`/contracts/${encodeURIComponent(contract.number)}/amendments`,
    { kind, changes, reason: reason.trim(), effective_from: effective, submit: true }),
  { success: (a) => `${a.number} raised – awaiting ${(a.changes.approvalChain ?? []).map(label).join(' → ')}`, onSuccess: onClose });

  const updateLine = (line: number, patch: Partial<LineDraft>) => setLines((ls) => ({ ...ls, [line]: { ...(ls[line] ?? { price: '', qty: '' }), ...patch } }));
  const clauseOptions = [{ value: '', label: '— no clause change —' }, ...contract.clauses.map((c) => ({ value: c.code, label: `${c.code} · ${c.title}` }))];

  return (
    <Dialog open title={terminating ? `Terminate ${contract.number}` : `Amend ${contract.number} (v${contract.version ?? 1})`} onClose={onClose}>
      <div className="space-y-4">
        {!terminating && (
          <Field label="Kind of amendment">{(id) => (
            <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as AmendKind)}
              options={(['VARIATION', 'EXTENSION', 'TERMS'] as AmendKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
          )}</Field>
        )}

        {kind === 'VARIATION' && (
          <div className="space-y-2">
            {contract.lines.map((l) => {
              const price = currentPrice(contract, l.id, priceOn);
              return (
                <div key={l.id} className="rounded-lg border border-slate-200 p-3">
                  <p className="text-sm font-medium">Line {l.line_no} · {l.description}</p>
                  <p className="text-xs text-slate-500">Current price {inr(price)} on {date(priceOn)} · target {qty(l.target_qty, l.uom)} · released {qty(l.released_qty)}</p>
                  <div className="mt-2 grid gap-3 md:grid-cols-2">
                    <Field label="New unit price (₹)" hint="Leave empty to keep">{(id) => <Input id={id} type="number" min="0" step="0.01" value={lines[l.line_no]?.price ?? ''}
                      onChange={(e) => updateLine(l.line_no, { price: e.target.value })} placeholder={price ? String(price / 100) : ''} />}</Field>
                    <Field label={`New target quantity (${l.uom})`} hint={`Not below the released ${qty(l.released_qty)}`}>{(id) => <Input id={id} type="number" min="0"
                      value={lines[l.line_no]?.qty ?? ''} onChange={(e) => updateLine(l.line_no, { qty: e.target.value })} placeholder={String(Number(l.target_qty))} />}</Field>
                  </div>
                </div>
              );
            })}
            <p className="text-xs text-slate-500">A new price adds a price-validity period from the effective date; earlier periods are never re-priced, so open releases keep their price.</p>
          </div>
        )}

        {kind === 'EXTENSION' && (
          <Field label="New end date" hint={`Currently ${date(contract.valid_to)}. Renewal notice and expiry timers move with it.`}>
            {(id) => <Input id={id} type="date" min={addDays(contract.valid_to, 1)} value={validTo} onChange={(e) => setValidTo(e.target.value)} />}
          </Field>
        )}

        {kind === 'TERMS' && (
          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Payment terms">{(id) => <Input id={id} maxLength={10} value={terms.paymentTerms} onChange={(e) => setTerms({ ...terms, paymentTerms: e.target.value.toUpperCase() })} />}</Field>
              <Field label="Incoterms">{(id) => <Input id={id} maxLength={40} value={terms.incoterms} onChange={(e) => setTerms({ ...terms, incoterms: e.target.value })} />}</Field>
              <Field label="Over-delivery tolerance (%)">{(id) => <Input id={id} type="number" min="0" max="100" step="0.1" value={terms.over} onChange={(e) => setTerms({ ...terms, over: e.target.value })} />}</Field>
              <Field label="Under-delivery tolerance (%)">{(id) => <Input id={id} type="number" min="0" max="100" step="0.1" value={terms.under} onChange={(e) => setTerms({ ...terms, under: e.target.value })} />}</Field>
              <Field label="Price tolerance (%)">{(id) => <Input id={id} type="number" min="0" max="100" step="0.1" value={terms.price} onChange={(e) => setTerms({ ...terms, price: e.target.value })} />}</Field>
            </div>
            <Field label="Clause">{(id) => <Select id={id} value={clause.code} options={clauseOptions}
              onChange={(e) => setClause({ code: e.target.value, text: contract.clauses.find((c) => c.code === e.target.value)?.text ?? '' })} />}</Field>
            {clause.code && <Field label="New clause text">{(id) => <Textarea id={id} value={clause.text} onChange={(e) => setClause({ ...clause, text: e.target.value })} />}</Field>}
          </div>
        )}

        {kind === 'TERMINATION' && (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4" checked={forCause} onChange={(e) => setForCause(e.target.checked)} />
              Termination for cause (breach) – the notice period does not apply
            </label>
            <p className="text-xs text-slate-500">From the effective date the contract stops pricing purchase orders and drops out of quota splits; open POs are flagged to the buyer.</p>
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-2">
          <Field label={terminating ? 'Termination effective from' : 'Effective from'} hint={terminating ? 'First day the contract is no longer in force' : 'Future dates are applied automatically on that day'}>
            {(id) => <Input id={id} type="date" min={todayIst()} value={effective} onChange={(e) => setEffective(e.target.value)} />}
          </Field>
        </div>
        <Field label="Business reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder={terminating ? 'e.g. Repeated quality breach; 8D not closed' : 'e.g. Q3 cost-down agreed in negotiation on …'} />}</Field>

        <div className="rounded-lg border border-slate-200 p-3" aria-live="polite">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Preview {planning && <span className="font-normal normal-case text-slate-400">· checking…</span>}</p>
          {planError ? <ProblemBox error={planError} /> : plan ? (
            <div className="space-y-2 text-sm">
              <ChangeTable kind={plan.kind} before={plan.before} after={{ ...plan.after, ...(plan.kind === 'TERMINATION' ? plan.changes : {}) }} />
              <p>
                Value change {delta(plan.valueDeltaMinor)} · version v{plan.fromVersion} → v{plan.fromVersion + 1} · approval{' '}
                <span className="font-semibold">{plan.approvalChain.map(label).join(' → ')}</span>{' '}
                <span className="text-slate-500">({plan.band === 'termination' ? 'termination route' : `${plan.band} ${inr(plan.thresholdMinor)}`})</span>
              </p>
              {plan.kind === 'TERMINATION' && (
                <>
                  <p className="text-slate-600">Without cause the earliest date is {date(plan.earliestWithoutCause)} ({plan.noticeDays} days&apos; notice).</p>
                  {plan.openPurchaseOrders?.length ? (
                    <p className="text-amber-800">Open POs to be flagged: {plan.openPurchaseOrders.map((p, i) => (
                      <Fragment key={p.number}>{i > 0 && ', '}<Link className="font-medium hover:underline" href={`/pic/purchase-orders/${encodeURIComponent(p.number)}`}>{p.number}</Link> ({label(p.status)})</Fragment>
                    ))}</p>
                  ) : <p className="text-slate-600">No open purchase orders reference this contract.</p>}
                </>
              )}
              <p className="font-mono text-[11px] text-slate-400">{plan.ruleSet}</p>
            </div>
          ) : <p className="text-sm text-slate-500">Enter the change to see its effect.</p>}
        </div>

        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={terminating ? 'danger' : 'primary'} disabled={!plan || reason.trim().length < 3} busy={create.isPending} onClick={() => create.mutate()}>
            {terminating ? 'Submit termination for approval' : 'Submit amendment for approval'}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- terminated / amended banner for the facts block
export function AmendmentSummary({ contractNumber }: { contractNumber: string }) {
  const { data } = useApi<Listing>(`/contracts/${encodeURIComponent(contractNumber)}/amendments`);
  const pending = data?.items.find((a) => PENDING.includes(a.status));
  if (!pending) return null;
  return (
    <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
      {pending.number} ({label(pending.kind)}) is {label(pending.status)}{pending.status === 'APPROVED' ? ` – takes effect on ${date(pending.effective_from)}` : ''}.
    </p>
  );
}

export function useAmendmentRule(contractNumber: string | undefined) {
  const { data } = useApi<Listing>(contractNumber ? `/contracts/${encodeURIComponent(contractNumber)}/amendments` : null);
  return data?.rule;
}

