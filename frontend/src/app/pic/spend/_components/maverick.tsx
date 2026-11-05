'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, date, dateTime, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';
import { LevelChip, SpendProblem } from './shared';

type Hit = {
  id: string; number: string; rule: string; status: string; lifecycle: string; disposition: string | null; reasonCode: string | null; invoice: string; po: string | null;
  supplier: string | null; category: string; plant: string | null; amountMinor: number; amountGroupMinor: number | null; currency: string | null; savingsAtRiskMinor: number | null;
  ownerRole: string; ownerId: string | null; dueAt: string | null; overdue: boolean; escalationLevel: number; escalatedTo: string | null; ageDays: number | null; comment: string | null;
  recoveredMinor: number | null; resolvedAt: string | null;
};
type HitSummary = {
  byStatus: Record<string, number>; byRule: Record<string, { count: number; open: number; valueMinor: number }>; openByOwnerRole: Record<string, number>; open: number; overdue: number;
  openValueMinor: number; savingsAtRiskMinor: number; recoveredMinor: number;
};
type Worklist = { total: number; hits: Hit[]; summary: HitSummary };
type RuleVersion = { version: string; effectiveFrom: string; effectiveTo: string | null; change: Record<string, unknown> };
type Rule = {
  code: string; name: string; description: string; active: boolean; severity: string; ownerRole: string; slaDays: number | null; escalateRole: string | null; hits: number; versions: RuleVersion[];
};
type Rules = { rules: Rule[]; reasonCodes: string[]; dispositions: string[] };
type Offenders = {
  since: string; minHits: number; totalHits: number;
  suppliers: { supplier: string; name: string | null; hits: number; rules: string[]; valueMinor: number; savingsAtRiskMinor: number; open: number; last: string | null }[];
  categories: { category: string; hits: number; rules: string[]; valueMinor: number; savingsAtRiskMinor: number; open: number; last: string | null }[];
};

const STATUSES = [
  { value: 'OPEN', label: 'Open' }, { value: 'RECOVERY_OPEN', label: 'Recovery open' }, { value: 'DISPOSED', label: 'Disposed' }, { value: 'RESOLVED', label: 'Resolved' }, { value: '', label: 'All statuses' },
];
const DISPOSITIONS = [
  { value: 'ACCEPTED_EXCEPTION', label: 'Accepted exception – justified, no action' },
  { value: 'RECOVERY', label: 'Recovery – recover the overpayment from the supplier' },
  { value: 'POLICY_BREACH', label: 'Policy breach – escalate to the requester’s manager' },
  { value: 'FALSE_POSITIVE', label: 'False positive – the rule should not have fired' },
];
const ROLES = ['CATEGORY_MANAGER', 'PROCUREMENT_HEAD', 'CPO', 'FINANCE_CONTROLLER'];
const PAGE = 50;

/** SPD-06 maverick spend: the worklist with SLA and escalation, recovery resolution, repeat offenders and the effective-dated rule versions. */
export function MaverickTab() {
  return (
    <Tabs label="Maverick views" tabs={[
      { id: 'worklist', label: 'Worklist', content: <Worklist /> },
      { id: 'offenders', label: 'Repeat offenders', content: <Offenders /> },
      { id: 'rules', label: 'Rules and versions', content: <RulesView /> },
    ]} />
  );
}

function Worklist() {
  const { scopes, roles } = useMe();
  const meId = useApi<{ userId: string }>('/me').data?.userId;
  // The platform lets the hit's owner, the owner role, the procurement head, the CPO and the finance controller act on it.
  const mayAct = (h: Hit) => h.ownerId === meId || roles.includes(h.ownerRole) || roles.some((r) => ['PROCUREMENT_HEAD', 'CPO', 'FINANCE_CONTROLLER'].includes(r));
  const [status, setStatus] = useState('OPEN');
  const [rule, setRule] = useState('');
  const [overdue, setOverdue] = useState('');
  const [mine, setMine] = useState(false);
  const [supplier, setSupplier] = useState('');
  const [offset, setOffset] = useState(0);
  const [disposing, setDisposing] = useState<Hit | null>(null);
  const [resolving, setResolving] = useState<Hit | null>(null);
  const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  if (status) qs.set('status', status);
  if (rule) qs.set('rule', rule);
  if (overdue === 'true') qs.set('overdue', 'true');
  if (mine) qs.set('owner', 'me');
  if (supplier.trim()) qs.set('supplier', supplier.trim());
  const { data, isLoading, error } = useApi<Worklist>(`/spend/maverick/worklist?${qs.toString()}`);
  const rules = useApi<Rules>('/spend/maverick-rules');
  const escalate = useCommand(() => api.post<{ escalated: { number: string; level: number; to: string }[] }>('/spend/maverick/escalate', {}), {
    success: (r) => (r.escalated.length ? `${r.escalated.length} hit(s) escalated: ${r.escalated.slice(0, 3).map((e) => `${e.number} to ${label(e.to)}`).join(', ')}${r.escalated.length > 3 ? ', …' : ''}` : 'No hit is past its SLA'),
  });
  const ruleList = rules.data?.rules ?? [];
  const ruleName = (code: string) => ruleList.find((r) => r.code === code)?.name ?? label(code);
  const sum = data?.summary;
  const reset = () => setOffset(0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Every hit has an owner, a due date by severity (critical 3, high 5, medium 10, low 15 days) and the savings at risk. A hit past its due date is escalated to the rule’s escalation role, at most twice.
          Accepting an exception or marking a false positive needs a reason code.
        </p>
        {scopes.includes('admin:integration') && (
          <Button busy={escalate.isPending} onClick={() => escalate.mutate()}>Escalate overdue hits now</Button>
        )}
      </div>
      {escalate.error && <ProblemBox error={escalate.error} />}
      {sum && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
          <Kpi label="Open hits" value={sum.open} hint={crore(sum.openValueMinor)} tone={sum.open ? 'warn' : 'good'} />
          <Kpi label="Past SLA" value={sum.overdue} tone={sum.overdue ? 'bad' : 'good'} hint="open and past the due date" />
          <Kpi label="Savings at risk" value={crore(sum.savingsAtRiskMinor)} hint="open hits: paid above contract" tone={sum.savingsAtRiskMinor ? 'warn' : 'default'} />
          <Kpi label="Recovered" value={crore(sum.recoveredMinor)} tone="good" hint={`${sum.byStatus.RECOVERY_OPEN ?? 0} in recovery · ${sum.byStatus.RESOLVED ?? 0} resolved`} />
          <Kpi label="Open by owner" value={<span className="text-sm">{Object.entries(sum.openByOwnerRole).map(([r, n]) => `${label(r)} ${n}`).join(' · ') || '–'}</span>} />
        </div>
      )}
      <Card title="Filter">
        <div className="grid gap-3 md:grid-cols-5">
          <Field label="Status">{(id) => <Select id={id} value={status} onChange={(e) => { setStatus(e.target.value); reset(); }} options={STATUSES} />}</Field>
          <Field label="Rule">{(id) => (
            <Select id={id} value={rule} onChange={(e) => { setRule(e.target.value); reset(); }}
              options={[{ value: '', label: 'All rules' }, ...ruleList.map((r) => ({ value: r.code, label: `${r.name} (${r.severity})` }))]} />
          )}</Field>
          <Field label="SLA">{(id) => <Select id={id} value={overdue} onChange={(e) => { setOverdue(e.target.value); reset(); }} options={[{ value: '', label: 'All' }, { value: 'true', label: 'Open and past SLA' }]} />}</Field>
          <Field label="Supplier code">{(id) => <Input id={id} value={supplier} onChange={(e) => { setSupplier(e.target.value); reset(); }} />}</Field>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={mine} onChange={(e) => { setMine(e.target.checked); reset(); }} /> Only mine and my roles’</label>
        </div>
      </Card>
      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : (
        <Card title={`Maverick hits (${data?.total ?? 0})`} actions={<span className="text-xs text-slate-500">largest amount first</span>}>
          <DataTable<Hit> caption="Maverick hits" rows={data?.hits ?? []} empty="No maverick hits for this filter" columns={[
            { key: 'number', header: 'Hit', render: (h) => <span className="font-mono text-xs font-semibold">{h.number}</span> },
            { key: 'rule', header: 'Rule', className: 'min-w-[170px]', render: (h) => {
              const r = ruleList.find((x) => x.code === h.rule);
              return <span>{ruleName(h.rule)}{r && <span className="ml-1 align-middle"><LevelChip level={r.severity} /></span>}</span>;
            } },
            { key: 'category', header: 'Category', render: (h) => <span className="font-mono text-xs">{h.category}</span> },
            { key: 'supplier', header: 'Supplier', render: (h) => (h.supplier ? <Link href={`/pic/suppliers/${encodeURIComponent(h.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{h.supplier}</Link> : '–') },
            { key: 'invoice', header: 'Invoice / PO', render: (h) => <span className="font-mono text-xs">{h.invoice}<br /><span className="text-slate-500">{h.po ?? 'no PO'}</span></span> },
            { key: 'amountMinor', header: 'Amount', align: 'right', render: (h) => <span>{inr(h.amountGroupMinor ?? h.amountMinor)}{h.savingsAtRiskMinor ? <span className="block text-xs text-amber-700">at risk {inr(h.savingsAtRiskMinor)}</span> : null}</span> },
            { key: 'ownerRole', header: 'Owner', render: (h) => <span>{label(h.ownerRole)}{h.escalationLevel > 0 && <span className="block text-xs font-medium text-amber-700">escalated ×{h.escalationLevel}{h.escalatedTo ? ` to ${label(h.escalatedTo)}` : ''}</span>}</span> },
            { key: 'dueAt', header: 'Due', render: (h) => (
              <span className={h.overdue ? 'font-semibold text-red-700' : 'text-slate-700'}>{h.dueAt ? date(h.dueAt) : '–'}{h.overdue && <span className="block text-[11px] uppercase">past SLA</span>}</span>
            ) },
            { key: 'status', header: 'Status', render: (h) => (
              <span><StatusChip status={h.status} />
                {h.disposition && <span className="mt-0.5 block text-xs text-slate-500">{label(h.disposition)}{h.reasonCode ? ` · ${label(h.reasonCode)}` : ''}</span>}
                {h.status === 'RESOLVED' && <span className="mt-0.5 block text-xs text-emerald-700">recovered {inr(h.recoveredMinor ?? 0)} · {dateTime(h.resolvedAt)}</span>}</span>
            ) },
            { key: 'actions', header: '', render: (h) => (h.status === 'OPEN' || h.status === 'RECOVERY_OPEN') && !mayAct(h)
              ? <span className="block max-w-[160px] text-xs text-slate-500">Owned by the {label(h.ownerRole).toLowerCase()}</span>
              : h.status === 'OPEN' ? <Button onClick={() => setDisposing(h)} aria-label={`Disposition ${h.number}`}>Disposition</Button>
                : h.status === 'RECOVERY_OPEN' ? <Button variant="primary" onClick={() => setResolving(h)} aria-label={`Resolve recovery of ${h.number}`}>Resolve recovery</Button>
                  : h.comment ? <span className="block max-w-[200px] text-xs text-slate-600">{h.comment}</span> : null },
          ]} />
          {data && data.total > PAGE && (
            <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
              <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</Button>
              <span>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
              <Button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
            </div>
          )}
        </Card>
      )}
      {disposing && <DispositionDialog hit={disposing} ruleName={ruleName(disposing.rule)} reasonCodes={rules.data?.reasonCodes ?? []} onClose={() => setDisposing(null)} />}
      {resolving && <ResolveDialog hit={resolving} onClose={() => setResolving(null)} />}
    </div>
  );
}

function DispositionDialog({ hit, ruleName, reasonCodes, onClose }: { hit: Hit; ruleName: string; reasonCodes: string[]; onClose: () => void }) {
  const [disposition, setDisposition] = useState('ACCEPTED_EXCEPTION');
  const [reasonCode, setReasonCode] = useState('');
  const [comment, setComment] = useState('');
  const needsReason = disposition === 'ACCEPTED_EXCEPTION' || disposition === 'FALSE_POSITIVE';
  const ok = comment.trim().length >= 5 && (!needsReason || !!reasonCode);
  const dispose = useCommand(() => api.post<Hit>(`/spend/maverick-hits/${hit.id}/disposition`, { disposition, comment: comment.trim(), reason_code: needsReason ? reasonCode : undefined }), {
    success: (h) => `${hit.number} ${h.status === 'RECOVERY_OPEN' ? 'sent for recovery' : 'disposed'} as ${label(disposition).toLowerCase()}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Disposition – ${hit.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">
        {ruleName} · {hit.category} · {inr(hit.amountGroupMinor ?? hit.amountMinor)} on invoice <span className="font-mono">{hit.invoice}</span>. Owned by the {label(hit.ownerRole).toLowerCase()};
        the procurement head, CPO and finance controller can also dispose. Accepting an exception above the tenant limit needs the procurement head or CPO.
      </p>
      <div className="grid gap-3">
        <Field label="Disposition">{(id) => <Select id={id} value={disposition} onChange={(e) => setDisposition(e.target.value)} options={DISPOSITIONS} />}</Field>
        {needsReason && (
          <Field label="Reason code" required hint="Required for accepted exceptions and false positives">{(id, d) => (
            <Select id={id} aria-describedby={d} value={reasonCode} onChange={(e) => setReasonCode(e.target.value)}
              options={[{ value: '', label: 'Choose a reason code…' }, ...reasonCodes.map((c) => ({ value: c, label: label(c) }))]} />
          )}</Field>
        )}
        <Field label="Comment" required hint="At least 5 characters. Kept in the audit trail.">{(id, d) => (
          <Textarea id={id} aria-describedby={d} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Emergency breakdown purchase approved by the plant head; PO raised afterwards" />
        )}</Field>
      </div>
      {dispose.error && <div className="mt-3"><ProblemBox error={dispose.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!ok} busy={dispose.isPending} onClick={() => dispose.mutate()}>Record disposition</Button>
      </div>
    </Dialog>
  );
}

function ResolveDialog({ hit, onClose }: { hit: Hit; onClose: () => void }) {
  const value = hit.amountGroupMinor ?? hit.amountMinor;
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const minor = amount.trim() && Number.isFinite(Number(amount)) && Number(amount) >= 0 ? rupeesToMinor(amount) : null;
  const tooMuch = minor !== null && minor > Math.abs(value);
  const resolve = useCommand(() => api.post<Hit>(`/spend/maverick-hits/${hit.id}/resolve`, { recovered_minor: minor, note: note.trim() }), {
    success: `${hit.number} resolved: ${minor !== null ? inr(minor) : ''} recovered`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Resolve recovery – ${hit.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">The hit is for {inr(value)}. Enter what the supplier credited or refunded; the hit closes as resolved.</p>
      <div className="grid gap-3">
        <Field label="Amount recovered (₹)" required error={tooMuch ? `The recovery cannot exceed the hit (${inr(value)})` : undefined} hint="Zero is allowed when nothing could be recovered">
          {(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </Field>
        <Field label="How was it recovered" required hint="Credit note, refund or set-off; at least 5 characters">{(id, d) => <Textarea id={id} aria-describedby={d} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
      {resolve.error && <div className="mt-3"><ProblemBox error={resolve.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={minor === null || tooMuch || note.trim().length < 5} busy={resolve.isPending} onClick={() => resolve.mutate()}>Resolve</Button>
      </div>
    </Dialog>
  );
}

function Offenders() {
  const [months, setMonths] = useState('12');
  const [minHits, setMinHits] = useState('3');
  const m = Math.min(60, Math.max(1, Number(months) || 12));
  const h = Math.min(100, Math.max(1, Number(minHits) || 3));
  const { data, isLoading, error } = useApi<Offenders>(`/spend/maverick/repeat-offenders?months=${m}&min_hits=${h}`);
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">Suppliers and categories with repeated hits in the window. A supplier that appears here against several rules is a conversation for the category manager, not a string of dispositions.</p>
      <Card title="Window">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Months back (1-60)">{(id) => <Input id={id} type="number" min={1} max={60} value={months} onChange={(e) => setMonths(e.target.value)} />}</Field>
          <Field label="At least this many hits">{(id) => <Input id={id} type="number" min={1} max={100} value={minHits} onChange={(e) => setMinHits(e.target.value)} />}</Field>
        </div>
      </Card>
      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : data && (
        <>
          <p className="text-xs text-slate-600">{data.totalHits.toLocaleString('en-IN')} hits since {date(data.since)}; showing those with {data.minHits} or more.</p>
          <Card title="Suppliers">
            <DataTable<Offenders['suppliers'][number] & { id: string }> caption="Repeat-offender suppliers" empty="No supplier reaches the threshold" rows={data.suppliers.map((s) => ({ ...s, id: s.supplier }))} columns={[
              { key: 'supplier', header: 'Supplier', render: (s) => <span><Link href={`/pic/suppliers/${encodeURIComponent(s.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{s.supplier}</Link><span className="block text-xs text-slate-500">{s.name}</span></span> },
              { key: 'hits', header: 'Hits', align: 'right', render: (s) => <span className="font-semibold">{s.hits}</span> },
              { key: 'open', header: 'Open', align: 'right' },
              { key: 'rules', header: 'Rules', render: (s) => s.rules.map((r) => label(r)).join(', ') },
              { key: 'valueMinor', header: 'Value', align: 'right', render: (s) => crore(s.valueMinor) },
              { key: 'savingsAtRiskMinor', header: 'At risk', align: 'right', render: (s) => crore(s.savingsAtRiskMinor) },
              { key: 'last', header: 'Latest', render: (s) => date(s.last) },
            ]} />
          </Card>
          <Card title="Categories">
            <DataTable<Offenders['categories'][number] & { id: string }> caption="Repeat-offender categories" empty="No category reaches the threshold" rows={data.categories.map((c) => ({ ...c, id: c.category }))} columns={[
              { key: 'category', header: 'Category', render: (c) => <span className="font-mono text-xs font-semibold">{c.category}</span> },
              { key: 'hits', header: 'Hits', align: 'right', render: (c) => <span className="font-semibold">{c.hits}</span> },
              { key: 'open', header: 'Open', align: 'right' },
              { key: 'rules', header: 'Rules', render: (c) => c.rules.map((r) => label(r)).join(', ') },
              { key: 'valueMinor', header: 'Value', align: 'right', render: (c) => crore(c.valueMinor) },
              { key: 'savingsAtRiskMinor', header: 'At risk', align: 'right', render: (c) => crore(c.savingsAtRiskMinor) },
              { key: 'last', header: 'Latest', render: (c) => date(c.last) },
            ]} />
          </Card>
        </>
      )}
    </div>
  );
}

function RulesView() {
  const { scopes } = useMe();
  const canVersion = scopes.includes('admin:rules');
  const [on, setOn] = useState('');
  const [versioning, setVersioning] = useState<Rule | null>(null);
  const { data, isLoading, error } = useApi<Rules>(`/spend/maverick-rules${on ? `?on=${on}` : ''}`);
  const rules = data?.rules ?? [];
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Nine rules. A change is never an edit: it is a new version with an effective date, and a hit is judged by the version in force on its document’s date.
        {!canVersion && ' Creating a version needs the rules administration permission (tenant administrator).'}
      </p>
      <Card title="As in force on">
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Date" hint="Blank: today">{(id, d) => <Input id={id} aria-describedby={d} type="date" value={on} onChange={(e) => setOn(e.target.value)} />}</Field>
        </div>
      </Card>
      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : (
        <Card title="Maverick rules">
          <DataTable<Rule & { id: string }> caption="Maverick rules and their versions" rows={rules.map((r) => ({ ...r, id: r.code }))} columns={[
            { key: 'code', header: 'Rule', className: 'min-w-[200px]', render: (r) => <span><span className="font-mono text-xs font-semibold">{r.code}</span><span className="block text-xs text-slate-600">{r.name}</span></span> },
            { key: 'description', header: 'What it detects', className: 'min-w-[240px] text-slate-600' },
            { key: 'active', header: 'Active', render: (r) => (r.active ? 'Yes' : <span className="font-medium text-red-700">Off</span>) },
            { key: 'severity', header: 'Severity', render: (r) => <LevelChip level={r.severity} /> },
            { key: 'ownerRole', header: 'Owner / escalation', render: (r) => <span>{label(r.ownerRole)}<span className="block text-xs text-slate-500">→ {label(r.escalateRole)}</span></span> },
            { key: 'slaDays', header: 'SLA', align: 'right', render: (r) => (r.slaDays ? `${r.slaDays} d` : '–') },
            { key: 'hits', header: 'Hits', align: 'right' },
            { key: 'versions', header: 'Versions', className: 'min-w-[200px]', render: (r) => (r.versions.length ? (
              <ul className="space-y-0.5 text-xs text-slate-700">
                {r.versions.map((v) => <li key={v.version}><span className="font-mono">{v.version}</span> from {date(v.effectiveFrom)}{v.effectiveTo ? ` to ${date(v.effectiveTo)}` : ''}: {Object.entries(v.change).map(([k, val]) => `${label(k.replace(/([A-Z])/g, '_$1'))} ${String(val)}`).join(', ')}</li>)}
              </ul>
            ) : <span className="text-xs text-slate-500">baseline only</span>) },
            { key: 'actions', header: '', render: (r) => (canVersion ? <Button onClick={() => setVersioning(r)} aria-label={`New version of ${r.code}`}>New version</Button> : null) },
          ]} />
        </Card>
      )}
      {versioning && <VersionDialog rule={versioning} onClose={() => setVersioning(null)} />}
    </div>
  );
}

function VersionDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const [from, setFrom] = useState('');
  const [reason, setReason] = useState('');
  const [active, setActive] = useState('');
  const [severity, setSeverity] = useState('');
  const [owner, setOwner] = useState('');
  const [sla, setSla] = useState('');
  const [escalate, setEscalate] = useState('');
  const slaNum = sla.trim() ? Number(sla) : null;
  const slaOk = slaNum === null || (Number.isInteger(slaNum) && slaNum >= 1 && slaNum <= 90);
  const something = active || severity || owner || sla.trim() || escalate;
  const save = useCommand(() => api.post<{ version: string }>(`/spend/maverick-rules/${rule.code}/versions`, {
    effective_from: from, reason: reason.trim(), active: active ? active === 'true' : undefined, severity: severity || undefined, owner_role: owner || undefined,
    sla_days: slaNum ?? undefined, escalate_role: escalate || undefined,
  }), { success: (r) => `${rule.code} ${r.version} created, effective ${from}`, onSuccess: onClose });
  const roleOptions = (blank: string) => [{ value: '', label: blank }, ...ROLES.map((r) => ({ value: r, label: label(r) }))];
  return (
    <Dialog open title={`New version of ${rule.code}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Leave a field unchanged to keep the value in force. The version applies to documents dated from the effective date.</p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Effective from" required>{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        <Field label="Active">{(id) => <Select id={id} value={active} onChange={(e) => setActive(e.target.value)} options={[{ value: '', label: `Unchanged (${rule.active ? 'on' : 'off'})` }, { value: 'true', label: 'Switch on' }, { value: 'false', label: 'Switch off' }]} />}</Field>
        <Field label="Severity">{(id) => <Select id={id} value={severity} onChange={(e) => setSeverity(e.target.value)}
          options={[{ value: '', label: `Unchanged (${rule.severity})` }, ...['Critical', 'High', 'Medium', 'Low'].map((s) => ({ value: s, label: s }))]} />}</Field>
        <Field label="SLA days (1-90)" error={slaOk ? undefined : 'A whole number of days from 1 to 90'}>{(id, d) => <Input id={id} aria-describedby={d} inputMode="numeric" placeholder={rule.slaDays ? `Unchanged (${rule.slaDays})` : ''} value={sla} onChange={(e) => setSla(e.target.value)} />}</Field>
        <Field label="Owner role">{(id) => <Select id={id} value={owner} onChange={(e) => setOwner(e.target.value)} options={roleOptions(`Unchanged (${label(rule.ownerRole)})`)} />}</Field>
        <Field label="Escalation role">{(id) => <Select id={id} value={escalate} onChange={(e) => setEscalate(e.target.value)} options={roleOptions(`Unchanged (${label(rule.escalateRole)})`)} />}</Field>
      </div>
      <div className="mt-3"><Field label="Reason" required hint="At least 5 characters; kept in the audit trail">{(id, d) => <Textarea id={id} aria-describedby={d} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>
      {save.error && <div className="mt-3"><ProblemBox error={save.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!from || reason.trim().length < 5 || !something || !slaOk} busy={save.isPending} onClick={() => save.mutate()}>Create version</Button>
      </div>
    </Dialog>
  );
}
