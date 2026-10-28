'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Kpi, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { LevelChip, SpendProblem } from './shared';

type Rule = { id: string; code: string; name: string; description: string; severity: string; owner_role: string; active: boolean };
type Hit = {
  id: string; number: string; rule_code: string; invoice_ref: string; po_ref: string | null; supplier: string | null; category: string;
  amount_minor: number; owner_role: string; owner_id: string | null; status: string; disposition: string | null; comment: string | null;
  disposed_at: string | null; created_at: string;
};
type MaverickView = { rules: Rule[]; hits: Hit[] };

const STATUSES = [
  { value: 'OPEN', label: 'Open' },
  { value: 'RECOVERY_OPEN', label: 'Recovery open' },
  { value: 'DISPOSED', label: 'Disposed' },
  { value: '', label: 'All statuses' },
];
const DISPOSITIONS = [
  { value: 'ACCEPTED_EXCEPTION', label: 'Accepted exception – justified, no action' },
  { value: 'RECOVERY', label: 'Recovery – recover the overpayment from the supplier' },
  { value: 'POLICY_BREACH', label: 'Policy breach – escalate to the requester’s manager' },
  { value: 'FALSE_POSITIVE', label: 'False positive – the rule should not have fired' },
];
const LIMIT = 200;

/** SPD-06 maverick hits: every hit has an owner and needs a disposition with a comment. */
export function MaverickTab() {
  const [status, setStatus] = useState('OPEN');
  const [rule, setRule] = useState('');
  const [disposing, setDisposing] = useState<Hit | null>(null);
  const qs = new URLSearchParams({ status, limit: String(LIMIT) });
  if (rule) qs.set('rule', rule);
  const { data, isLoading, error } = useApi<MaverickView>(`/spend/maverick?${qs.toString()}`);
  const rules = data?.rules ?? [];
  const ruleName = (code: string) => rules.find((r) => r.code === code)?.name ?? label(code);
  const hits = data?.hits ?? [];
  const total = hits.reduce((s, h) => s + Number(h.amount_minor), 0);

  return (
    <div className="space-y-6">
      <Card title="Filter">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Status">{(id) => <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)} options={STATUSES} />}</Field>
          <Field label="Rule">{(id) => (
            <Select id={id} value={rule} onChange={(e) => setRule(e.target.value)}
              options={[{ value: '', label: 'All rules' }, ...rules.map((r) => ({ value: r.code, label: `${r.name} (${r.severity})` }))]} />
          )}</Field>
        </div>
      </Card>

      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Hits shown" value={hits.length} hint={hits.length === LIMIT ? `largest ${LIMIT} by amount` : status ? label(status) : 'all statuses'} />
            <Kpi label="Amount" value={crore(total)} hint={inr(total)} tone={total && status === 'OPEN' ? 'warn' : 'default'} />
            <Kpi label="Rules active" value={rules.filter((r) => r.active).length} hint={`of ${rules.length} configured`} />
            <Kpi label="Critical rules hit" value={new Set(hits.filter((h) => rules.find((r) => r.code === h.rule_code)?.severity === 'Critical').map((h) => h.rule_code)).size} />
          </div>

          <Card title="Maverick hits" actions={<span className="text-xs text-slate-500">largest amount first</span>}>
            <DataTable<Hit> rows={hits} empty="No maverick hits for this filter" columns={[
              { key: 'number', header: 'Hit', render: (h) => <span className="font-mono text-xs font-semibold">{h.number}</span> },
              { key: 'rule_code', header: 'Rule', className: 'min-w-[180px]', render: (h) => {
                const r = rules.find((x) => x.code === h.rule_code);
                return <span>{ruleName(h.rule_code)}{r && <span className="ml-1 align-middle"><LevelChip level={r.severity} /></span>}</span>;
              } },
              { key: 'category', header: 'Category', render: (h) => <span className="font-mono text-xs">{h.category}</span> },
              { key: 'supplier', header: 'Supplier', render: (h) => (h.supplier ? <Link href={`/pic/suppliers/${encodeURIComponent(h.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{h.supplier}</Link> : '–') },
              { key: 'invoice_ref', header: 'Invoice / PO', render: (h) => <span className="font-mono text-xs">{h.invoice_ref}<br /><span className="text-slate-500">{h.po_ref ?? 'no PO'}</span></span> },
              { key: 'amount_minor', header: 'Amount', align: 'right', render: (h) => inr(h.amount_minor) },
              { key: 'owner_role', header: 'Owner', render: (h) => label(h.owner_role) },
              { key: 'status', header: 'Status', render: (h) => (
                <span><StatusChip status={h.status} />{h.disposition && <span className="mt-0.5 block text-xs text-slate-500">{label(h.disposition)} · {dateTime(h.disposed_at)}</span>}</span>
              ) },
              { key: 'actions', header: '', render: (h) => (h.status === 'OPEN' ? <Button onClick={() => setDisposing(h)}>Disposition</Button> : (
                h.comment ? <span className="block max-w-[220px] text-xs text-slate-600">{h.comment}</span> : null
              )) },
            ]} />
          </Card>

          <Card title="Maverick rules (tenant configuration)">
            <DataTable<Rule> rows={rules} columns={[
              { key: 'code', header: 'Code', render: (r) => <span className="font-mono text-xs">{r.code}</span> },
              { key: 'name', header: 'Rule' },
              { key: 'description', header: 'What it detects', className: 'min-w-[260px] text-slate-600' },
              { key: 'severity', header: 'Severity', render: (r) => <LevelChip level={r.severity} /> },
              { key: 'owner_role', header: 'Owner', render: (r) => label(r.owner_role) },
              { key: 'active', header: 'Active', render: (r) => (r.active ? 'Yes' : 'No') },
            ]} />
          </Card>
        </>
      )}

      {disposing && <DispositionDialog hit={disposing} ruleName={ruleName(disposing.rule_code)} onClose={() => setDisposing(null)} />}
    </div>
  );
}

function DispositionDialog({ hit, ruleName, onClose }: { hit: Hit; ruleName: string; onClose: () => void }) {
  const [disposition, setDisposition] = useState('ACCEPTED_EXCEPTION');
  const [comment, setComment] = useState('');
  const ok = comment.trim().length >= 5;
  const dispose = useCommand(() => api.post<Hit>(`/spend/maverick-hits/${hit.id}/disposition`, { disposition, comment: comment.trim() }), {
    success: (h) => `${hit.number} ${h.status === 'RECOVERY_OPEN' ? 'sent for recovery' : 'disposed'} as ${label(disposition).toLowerCase()}`, onSuccess: onClose });
  return (
    <Dialog open title={`Disposition – ${hit.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{ruleName} · {hit.category} · {inr(hit.amount_minor)} on invoice <span className="font-mono">{hit.invoice_ref}</span>.
        Owned by the {label(hit.owner_role).toLowerCase()}; the procurement head, CPO and finance controller can also dispose.</p>
      <div className="grid gap-3">
        <Field label="Disposition">{(id) => <Select id={id} value={disposition} onChange={(e) => setDisposition(e.target.value)} options={DISPOSITIONS} />}</Field>
        <Field label="Comment (required)" hint="At least 5 characters. The comment is kept in the audit trail.">{(id) => (
          <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Emergency breakdown purchase approved by plant head; PO raised retrospectively" />
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
