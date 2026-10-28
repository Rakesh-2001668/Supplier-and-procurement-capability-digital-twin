'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Facts, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date, dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { useSessionUser } from '../invoices/_components';

// ---------------------------------------------------------------- types
type Rule = { id: string; key: string; version: string; company_code: string | null; plant: string | null; category: string | null;
  purchase_type: string | null; effective_from: string; effective_to: string | null; body: unknown; description: string | null;
  created_at: string };
type SodRule = { id: string; code: string; action_a: string; action_b: string; scope: string; condition: string | null; risk: string; mode: string;
  description: string; active: boolean };
type SodViolation = { id: string; rule_code: string; attempted_action: string; conflicting_action: string; refs: Record<string, unknown>;
  outcome: string; created_at: string };
type Message = { id: string; target_system: string; direction: string; message_type: string; idempotency_key: string; object_type: string;
  object_ref: string | null; status: string; erp_doc_no: string | null; attempts: number; last_error: string | null; posted_at: string | null;
  next_attempt_at: string | null };
type AuditRow = { seq: number; ts: string; objectType: string; objectRef: string | null; action: string; actor: string; reason: string | null;
  ruleSetVersion: string | null; aiRef: string | null; hash: string };
type Verify = { valid: boolean; checked: number; head?: string | null; broken_at_seq?: number; event_id?: string };
type Tick = { events: number; integration: number; timers: number };

const scopeText = (r: Rule) => {
  const parts = [r.company_code && `company ${r.company_code}`, r.plant && `plant ${r.plant}`, r.category && `category ${r.category}`,
    r.purchase_type && `type ${r.purchase_type}`].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'All (tenant default)';
};

// ---------------------------------------------------------------- rules & thresholds (ADM-02)
type RuleForm = { key: string; version: string; effective_from: string; effective_to: string; company_code: string; plant: string;
  category: string; purchase_type: string; body: string; description: string };

function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
}

function NewRuleDialog({ from, onClose }: { from: Rule | null; onClose: () => void }) {
  const [f, setF] = useState<RuleForm>({
    key: from?.key ?? '', version: '', effective_from: today(), effective_to: '',
    company_code: from?.company_code ?? '', plant: from?.plant ?? '', category: from?.category ?? '', purchase_type: from?.purchase_type ?? '',
    body: from ? JSON.stringify(from.body, null, 2) : '{\n  \n}', description: from?.description ?? '',
  });
  const [invalid, setInvalid] = useState<string | null>(null);
  const cmd = useCommand((body: Record<string, unknown>) => api.post<Rule>('/admin/rules', body), {
    success: (r) => `Rule ${r.key} version ${r.version} created`, onSuccess: onClose,
  });
  const set = (k: keyof RuleForm) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.key.trim() || !f.version.trim() || !f.effective_from) { setInvalid('Key, version and effective-from date are required.'); return; }
    if (f.effective_to && f.effective_to < f.effective_from) { setInvalid('Effective-to must be on or after effective-from.'); return; }
    let body: unknown;
    try { body = JSON.parse(f.body); } catch (err) { setInvalid(`Body is not valid JSON: ${(err as Error).message}`); return; }
    if (!body || typeof body !== 'object' || Array.isArray(body)) { setInvalid('Body must be a JSON object, e.g. {"bands": [...]}'); return; }
    setInvalid(null);
    const opt = (v: string) => (v.trim() ? v.trim() : undefined);
    cmd.mutate({
      key: f.key.trim(), version: f.version.trim(), effective_from: f.effective_from, effective_to: opt(f.effective_to),
      company_code: opt(f.company_code), plant: opt(f.plant), category: opt(f.category), purchase_type: opt(f.purchase_type),
      body, description: opt(f.description),
    });
  }

  return (
    <Dialog open title={from ? `New version of ${from.key}` : 'New rule version'} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">
          Versions are never edited. Saving creates a new effective-dated version; documents already in flight keep the version
          they were created under, and new documents pick the most specific version effective on their date.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Rule key (required)">{(id) => <Input id={id} required value={f.key} onChange={set('key')} placeholder="e.g. PO-RELEASE" />}</Field>
          <Field label="Version (required)" hint={from ? `Current: ${from.version}` : undefined}>{(id) => <Input id={id} required value={f.version} onChange={set('version')} placeholder="e.g. 2026.2" />}</Field>
          <Field label="Effective from (required)">{(id) => <Input id={id} type="date" required value={f.effective_from} onChange={set('effective_from')} />}</Field>
          <Field label="Effective to" hint="Leave empty for open-ended">{(id) => <Input id={id} type="date" value={f.effective_to} onChange={set('effective_to')} />}</Field>
          <Field label="Company code" hint="Empty = all">{(id) => <Input id={id} value={f.company_code} onChange={set('company_code')} />}</Field>
          <Field label="Plant" hint="Empty = all">{(id) => <Input id={id} value={f.plant} onChange={set('plant')} />}</Field>
          <Field label="Category" hint="Empty = all">{(id) => <Input id={id} value={f.category} onChange={set('category')} />}</Field>
          <Field label="Purchase type" hint="Empty = all">{(id) => <Input id={id} value={f.purchase_type} onChange={set('purchase_type')} />}</Field>
        </div>
        <Field label="Rule body (JSON object, required)">
          {(id) => <Textarea id={id} required value={f.body} onChange={set('body')} spellCheck={false} className="min-h-[200px] font-mono text-xs" />}
        </Field>
        <Field label="Description">{(id) => <Input id={id} value={f.description} onChange={set('description')} />}</Field>
        {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={cmd.isPending}>Create version</Button>
        </div>
      </form>
    </Dialog>
  );
}

function RulesTab() {
  const { data, isLoading, error } = useApi<Rule[]>('/admin/rules');
  const [dialog, setDialog] = useState<{ from: Rule | null } | null>(null);
  return (
    <Card title="Rules & thresholds (ADM-02)" actions={<Button variant="primary" onClick={() => setDialog({ from: null })}>New version</Button>}>
      <p className="mb-3 text-sm text-slate-600">Approval bands, tolerances, budget controls and playbooks are data, not code. Each change is a new
        effective-dated version; in-flight documents keep the version they started with.</p>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <DataTable<Rule> rows={data ?? []} empty="No rule sets" columns={[
          { key: 'key', header: 'Key', render: (r) => <span className="font-mono text-xs font-semibold">{r.key}</span> },
          { key: 'version', header: 'Version', render: (r) => <span className="font-mono text-xs">{r.version}</span> },
          { key: 'scope', header: 'Scope', render: (r) => <span className="text-xs">{scopeText(r)}</span> },
          { key: 'effective_from', header: 'Effective', render: (r) => <span className="whitespace-nowrap text-xs">{date(r.effective_from)} → {r.effective_to ? date(r.effective_to) : 'open'}</span> },
          { key: 'description', header: 'Description', className: 'min-w-[180px]', render: (r) => r.description ?? '–' },
          { key: 'body', header: 'Body', render: (r) => (
            <details>
              <summary className="cursor-pointer text-xs font-medium text-[#1A56DB]">Show JSON</summary>
              <pre className="mt-1 max-h-72 max-w-md overflow-auto rounded bg-slate-50 p-2 font-mono text-[11px] text-slate-800">{JSON.stringify(r.body, null, 2)}</pre>
            </details>
          ) },
          { key: 'actions', header: '', render: (r) => <Button variant="ghost" onClick={() => setDialog({ from: r })}>New version</Button> },
        ]} />
      )}
      {dialog && <NewRuleDialog from={dialog.from} onClose={() => setDialog(null)} />}
    </Card>
  );
}

// ---------------------------------------------------------------- roles & SoD (ADM-04)
function SodTab() {
  const { data, isLoading, error } = useApi<{ rules: SodRule[]; violations: SodViolation[] }>('/admin/sod');
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  return (
    <div className="space-y-4">
      <Card title={`Segregation-of-duties rules (${data.rules.length})`}>
        <DataTable<SodRule> rows={data.rules} empty="No SoD rules" columns={[
          { key: 'code', header: 'Code', render: (r) => <span className="font-mono text-xs font-semibold">{r.code}</span> },
          { key: 'action_a', header: 'Action A', render: (r) => <span className="font-mono text-xs">{r.action_a}</span> },
          { key: 'action_b', header: 'Action B', render: (r) => <span className="font-mono text-xs">{r.action_b}</span> },
          { key: 'scope', header: 'Same', render: (r) => <span className="font-mono text-xs">{r.scope}</span> },
          { key: 'condition', header: 'Condition', render: (r) => r.condition ?? '–' },
          { key: 'risk', header: 'Risk' },
          { key: 'mode', header: 'Mode', render: (r) => <StatusChip status={r.mode} /> },
          { key: 'description', header: 'Description', className: 'min-w-[220px]' },
        ]} />
      </Card>
      <Card title={`Violations and blocks (${data.violations.length})`}>
        <DataTable<SodViolation> rows={data.violations} empty="No SoD conflicts have been attempted" columns={[
          { key: 'created_at', header: 'When', render: (r) => dateTime(r.created_at) },
          { key: 'rule_code', header: 'Rule', render: (r) => <span className="font-mono text-xs font-semibold">{r.rule_code}</span> },
          { key: 'attempted_action', header: 'Attempted', render: (r) => <span className="font-mono text-xs">{r.attempted_action}</span> },
          { key: 'conflicting_action', header: 'Conflicts with', render: (r) => <span className="font-mono text-xs">{r.conflicting_action}</span> },
          { key: 'refs', header: 'References', render: (r) => <span className="font-mono text-[11px]">{Object.entries(r.refs ?? {}).map(([k, v]) => `${k}: ${String(v)}`).join(' · ') || '–'}</span> },
          { key: 'outcome', header: 'Outcome', render: (r) => <StatusChip status={r.outcome} /> },
        ]} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- integration monitor (ADM-05)
const MSG_STATUSES = ['', 'PENDING', 'RETRY', 'DEAD_LETTER', 'POSTED'];
const REPLAYABLE = ['RETRY', 'DEAD_LETTER', 'PENDING'];

function IntegrationTab() {
  const [status, setStatus] = useState('');
  const list = useList<Message>(`/integration/messages${status ? `?status=${status}` : ''}`);
  const [replaying, setReplaying] = useState<string | null>(null);
  const replay = useCommand((id: string) => api.post<Message>(`/integration/messages/${id}/replay`), {
    success: (m) => `Replayed: ${m.object_ref ?? m.idempotency_key} is now ${label(m.status).toLowerCase()}`,
  });
  return (
    <Card title="Integration monitor (ADM-05)" actions={
      <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}
        options={MSG_STATUSES.map((s) => ({ value: s, label: s ? label(s) : 'All statuses' }))} />
    }>
      <p className="mb-3 text-sm text-slate-600">Outbound ERP postings with their idempotency key. A replay re-sends with the same key, so the ERP never
        double-posts.</p>
      <DataTable<Message>
        rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No integration messages"
        columns={[
          { key: 'target_system', header: 'Target', render: (r) => <span className="text-xs">{r.target_system}<br /><span className="text-slate-500">{label(r.direction)}</span></span> },
          { key: 'message_type', header: 'Type', render: (r) => label(r.message_type) },
          { key: 'idempotency_key', header: 'Idempotency key', render: (r) => <span className="font-mono text-[11px]">{r.idempotency_key}</span> },
          { key: 'object_ref', header: 'Object', render: (r) => r.object_ref ?? '–' },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
          { key: 'erp_doc_no', header: 'ERP doc', render: (r) => r.erp_doc_no ?? '–' },
          { key: 'attempts', header: 'Attempts', align: 'right' },
          { key: 'last_error', header: 'Last error', className: 'max-w-xs', render: (r) => (r.last_error ? <span className="text-xs text-red-800">{r.last_error}</span> : '–') },
          { key: 'posted_at', header: 'Posted', render: (r) => dateTime(r.posted_at) },
          { key: 'replay', header: '', render: (r) => REPLAYABLE.includes(r.status) ? (
            <Button busy={replay.isPending && replaying === r.id} disabled={replay.isPending}
              onClick={() => { setReplaying(r.id); replay.mutate(r.id); }}>Replay</Button>
          ) : null },
        ]}
      />
    </Card>
  );
}

// ---------------------------------------------------------------- audit explorer (ADM-06)
function AuditTab() {
  const [draft, setDraft] = useState({ object_type: '', action: '', actor: '', limit: '100' });
  const [applied, setApplied] = useState(draft);
  const qs = new URLSearchParams();
  Object.entries(applied).forEach(([k, v]) => { if (v.trim()) qs.set(k, v.trim()); });
  const { data, isLoading, error } = useApi<{ items: AuditRow[] }>(`/audit?${qs}`);
  const [verify, setVerify] = useState<{ busy: boolean; result?: Verify; error?: ApiError }>({ busy: false });

  async function runVerify() {
    setVerify({ busy: true });
    try {
      setVerify({ busy: false, result: await api.get<Verify>('/audit/verify') });
    } catch (e) {
      setVerify({ busy: false, error: e as ApiError });
    }
  }

  function apply(e: FormEvent) {
    e.preventDefault();
    setApplied(draft);
  }

  return (
    <div className="space-y-4">
      <Card title="Hash chain" actions={<Button variant="primary" busy={verify.busy} onClick={runVerify}>Verify hash chain</Button>}>
        <p className="text-sm text-slate-600">Every audit event stores the hash of the previous one. Verification recomputes the whole chain for this tenant;
          any altered or deleted row breaks it.</p>
        {verify.error && <div className="mt-3"><ProblemBox error={verify.error} /></div>}
        {verify.result && (verify.result.valid ? (
          <p role="status" className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
            ✓ Chain intact: {verify.result.checked} events verified. Head <span className="break-all font-mono text-xs">{verify.result.head ?? '–'}</span>
          </p>
        ) : (
          <p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
            ✕ Chain broken at sequence {verify.result.broken_at_seq} after {verify.result.checked} valid events
            {verify.result.event_id && <> (event <span className="font-mono text-xs">{verify.result.event_id}</span>)</>}.
          </p>
        ))}
      </Card>

      <Card title="Audit explorer (ADM-06)">
        <form onSubmit={apply} className="mb-4 grid gap-3 sm:grid-cols-5 sm:items-end">
          <Field label="Object type">{(id) => <Input id={id} value={draft.object_type} onChange={(e) => setDraft({ ...draft, object_type: e.target.value })} placeholder="e.g. PURCHASE_ORDER" />}</Field>
          <Field label="Action">{(id) => <Input id={id} value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} placeholder="e.g. APPROVED" />}</Field>
          <Field label="Actor contains">{(id) => <Input id={id} value={draft.actor} onChange={(e) => setDraft({ ...draft, actor: e.target.value })} placeholder="e.g. buyer" />}</Field>
          <Field label="Limit (max 500)">{(id) => <Input id={id} type="number" min={1} max={500} value={draft.limit} onChange={(e) => setDraft({ ...draft, limit: e.target.value })} />}</Field>
          <Button type="submit" variant="primary">Search</Button>
        </form>
        <DataTable<AuditRow> rows={(data?.items ?? []) as AuditRow[]} loading={isLoading} error={error} empty="No audit events match"
          columns={[
            { key: 'seq', header: 'Seq', align: 'right' },
            { key: 'ts', header: 'When', render: (r) => <span className="whitespace-nowrap">{dateTime(r.ts)}</span> },
            { key: 'objectType', header: 'Object', render: (r) => <span>{label(r.objectType)}<br /><span className="font-medium">{r.objectRef ?? '–'}</span></span> },
            { key: 'action', header: 'Action', render: (r) => <span className="font-mono text-xs">{r.action}</span> },
            { key: 'actor', header: 'Actor', render: (r) => <span className="text-xs">{r.actor}</span> },
            { key: 'reason', header: 'Reason', render: (r) => r.reason ?? '–' },
            { key: 'ruleSetVersion', header: 'Rule version', render: (r) => r.ruleSetVersion ?? '–' },
            { key: 'aiRef', header: 'AI ref', render: (r) => r.aiRef ?? '–' },
            { key: 'hash', header: 'Hash', render: (r) => <span className="font-mono text-[11px] text-slate-500">{r.hash}…</span> },
          ]} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- operations
function OpsTab() {
  const [last, setLast] = useState<{ at: string; result: Tick } | null>(null);
  const tick = useCommand(() => api.post<Tick>('/admin/ops/tick'), {
    success: 'Worker tick complete', onSuccess: (result) => setLast({ at: new Date().toISOString(), result }),
  });
  return (
    <Card title="Operations" actions={<Button variant="primary" busy={tick.isPending} onClick={() => tick.mutate()}>Run worker tick now</Button>}>
      <p className="text-sm text-slate-600">The background worker normally runs every 2 seconds: it relays outbox events, fires due timers
        (escalations, renewals) and retries pending ERP postings. Run one tick by hand when you want to see the effect immediately.</p>
      <ProblemBox error={tick.error} />
      {last && (
        <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
          <div className="rounded-lg border border-slate-200 px-3 py-2"><dt className="text-xs text-slate-500">Events relayed</dt><dd className="text-lg font-semibold tabular-nums">{last.result.events}</dd></div>
          <div className="rounded-lg border border-slate-200 px-3 py-2"><dt className="text-xs text-slate-500">ERP messages processed</dt><dd className="text-lg font-semibold tabular-nums">{last.result.integration}</dd></div>
          <div className="rounded-lg border border-slate-200 px-3 py-2"><dt className="text-xs text-slate-500">Timers fired</dt><dd className="text-lg font-semibold tabular-nums">{last.result.timers}</dd></div>
          <p className="col-span-3 text-xs text-slate-500">Last run {dateTime(last.at)}</p>
        </dl>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- organisation, calendars, currencies (ADM-01)
type Org = {
  tenant: { code: string; name: string; industryTemplate: string; templateName: string | null; baseCurrency: string; timezone: string };
  companyCodes: { code: string; name: string; gstin: string | null; currency: string; fiscalYearStartMonth: number }[];
  plants: { code: string; name: string; companyCode: string; stateCode: string | null; workingDays: number[] | null; holidays: string[];
    storageLocations: { code: string; name: string }[] }[];
  costObjects: { type: string; code: string; name: string; companyCode: string }[];
  currencies: { code: string; name: string; decimals: number; active: boolean }[];
  fxRates: { from: string; to: string; rate: string; validFrom: string; source: string }[];
};
// Python weekday numbering (0 = Monday), as stored on the plant calendar.
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function OrganisationTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<Org>('/admin/organisation');
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  return (
    <div className="space-y-4">
      <Card title="Organisation (ADM-01)">
        <Facts items={[
          ['Tenant', `${data.tenant.name} (${data.tenant.code})`], ['Industry template', data.tenant.templateName ?? label(data.tenant.industryTemplate)],
          ['Base currency', data.tenant.baseCurrency], ['Time zone', data.tenant.timezone],
        ]} />
      </Card>
      <Card title={`Company codes (${data.companyCodes.length})`}>
        <DataTable<Org['companyCodes'][number]> rows={data.companyCodes} empty="No company codes" columns={[
          { key: 'code', header: 'Code', render: (c) => <span className="font-mono text-xs font-semibold">{c.code}</span> },
          { key: 'name', header: 'Legal entity' },
          { key: 'gstin', header: 'GSTIN', render: (c) => <span className="font-mono text-xs">{c.gstin ?? '–'}</span> },
          { key: 'currency', header: 'Currency' },
          { key: 'fiscalYearStartMonth', header: 'Fiscal year starts', render: (c) => MONTHS[c.fiscalYearStartMonth - 1] ?? c.fiscalYearStartMonth },
        ]} />
      </Card>
      <Card title={`Plants, calendars and storage locations (${data.plants.length})`}>
        <DataTable<Org['plants'][number]> rows={data.plants} empty="No plants" columns={[
          { key: 'code', header: 'Plant', render: (p) => <span><span className="font-mono text-xs font-semibold">{p.code}</span> {p.name}</span> },
          { key: 'companyCode', header: 'Company' },
          { key: 'stateCode', header: 'GST state', render: (p) => p.stateCode ?? '–' },
          { key: 'workingDays', header: 'Working days', render: (p) => <span className="text-xs">{(p.workingDays ?? []).map((d) => WEEKDAYS[d] ?? d).join(' ') || '–'}</span> },
          { key: 'holidays', header: 'Holidays', render: (p) => <span className="text-xs">{p.holidays.length ? p.holidays.map((h) => date(h)).join(' · ') : '–'}</span> },
          { key: 'storageLocations', header: 'Storage locations', render: (p) => (
            <ul className="text-xs">{p.storageLocations.map((s) => <li key={s.code}><span className="font-mono">{s.code}</span> {s.name}</li>)}</ul>
          ) },
        ]} />
      </Card>
      <Card title={`Cost objects (${data.costObjects.length})`}>
        <DataTable<Org['costObjects'][number] & { id: string }> rows={data.costObjects.map((c) => ({ ...c, id: `${c.type}-${c.code}` }))} empty="No cost objects" columns={[
          { key: 'type', header: 'Type', render: (c) => label(c.type) },
          { key: 'code', header: 'Code', render: (c) => <span className="font-mono text-xs font-semibold">{c.code}</span> },
          { key: 'name', header: 'Name' },
          { key: 'companyCode', header: 'Company' },
        ]} />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Currencies (${data.currencies.length})`}>
          <DataTable<Org['currencies'][number]> rows={data.currencies} empty="No currencies" columns={[
            { key: 'code', header: 'Code', render: (c) => <span className="font-mono text-xs font-semibold">{c.code}</span> },
            { key: 'name', header: 'Name' },
            { key: 'decimals', header: 'Decimals', align: 'right' },
            { key: 'active', header: 'Status', render: (c) => <StatusChip status={c.active ? 'ACTIVE' : 'INACTIVE'} /> },
          ]} />
        </Card>
        <Card title={`FX rates (${data.fxRates.length})`}>
          <p className="mb-3 text-xs text-slate-500">Spend is normalised to {data.tenant.baseCurrency} with the latest rate valid on the document date. Rates are never edited; add a later-dated rate.</p>
          <DataTable<Org['fxRates'][number] & { id: string }> rows={data.fxRates.map((r) => ({ ...r, id: `${r.from}${r.to}${r.validFrom}` }))} empty="No FX rates yet" columns={[
            { key: 'pair', header: 'Pair', render: (r) => <span className="font-mono text-xs font-semibold">{r.from}/{r.to}</span> },
            { key: 'rate', header: 'Rate', align: 'right', render: (r) => <span className="font-mono text-xs">{r.rate}</span> },
            { key: 'validFrom', header: 'Valid from', render: (r) => date(r.validFrom) },
            { key: 'source', header: 'Source' },
          ]} />
          {isAdmin && <FxRateForm currencies={data.currencies.filter((c) => c.active).map((c) => c.code)} base={data.tenant.baseCurrency} />}
        </Card>
      </div>
    </div>
  );
}

function FxRateForm({ currencies, base }: { currencies: string[]; base: string }) {
  const [f, setF] = useState({ from_ccy: currencies.find((c) => c !== base) ?? '', to_ccy: base, rate: '', valid_from: today(), source: 'RBI reference rate' });
  const [invalid, setInvalid] = useState<string | null>(null);
  const cmd = useCommand((body: Record<string, unknown>) => api.post('/admin/fx-rates', body), {
    success: `${f.from_ccy}/${f.to_ccy} rate added`, onSuccess: () => setF((x) => ({ ...x, rate: '' })),
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const options = currencies.map((c) => ({ value: c, label: c }));
  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.from_ccy === f.to_ccy) { setInvalid('From and to currency must differ.'); return; }
    if (!f.rate.trim() || Number.isNaN(Number(f.rate)) || Number(f.rate) <= 0) { setInvalid('Rate must be a positive number.'); return; }
    if (!f.valid_from || !f.source.trim()) { setInvalid('Valid-from date and source are required.'); return; }
    setInvalid(null);
    cmd.mutate({ from_ccy: f.from_ccy, to_ccy: f.to_ccy, rate: f.rate.trim(), valid_from: f.valid_from, source: f.source.trim() });
  }
  return (
    <form onSubmit={submit} className="mt-4 space-y-3 border-t border-slate-100 pt-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Add rate</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="From">{(id) => <Select id={id} value={f.from_ccy} onChange={set('from_ccy')} options={options} />}</Field>
        <Field label="To">{(id) => <Select id={id} value={f.to_ccy} onChange={set('to_ccy')} options={options} />}</Field>
        <Field label={`Rate (1 ${f.from_ccy} = ? ${f.to_ccy})`}>{(id) => <Input id={id} inputMode="decimal" required value={f.rate} onChange={set('rate')} placeholder="e.g. 83.2450" />}</Field>
        <Field label="Valid from">{(id) => <Input id={id} type="date" required value={f.valid_from} onChange={set('valid_from')} />}</Field>
        <div className="sm:col-span-2"><Field label="Source">{(id) => <Input id={id} required value={f.source} onChange={set('source')} />}</Field></div>
      </div>
      {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
      <ProblemBox error={cmd.error} />
      <div className="flex justify-end"><Button type="submit" variant="primary" busy={cmd.isPending}>Add FX rate</Button></div>
    </form>
  );
}

// ---------------------------------------------------------------- users & roles (ADM-04)
type AppUserRow = { id: string; email: string; name: string; roles: string[]; active: boolean; mfaEnrolled: boolean; supplierUser: boolean;
  attributes: Record<string, unknown> };
// The role catalogue comes from the backend (GET /admin/roles); assignment re-validates SoD role pairs and MFA for sensitive roles.
type RoleRow = { role: string; scopes: string[] };
const SENSITIVE = ['TENANT_ADMIN', 'FINANCE_CONTROLLER', 'CPO'];

function UsersTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<AppUserRow[]>(isAdmin ? '/admin/users' : null);
  const [editing, setEditing] = useState<AppUserRow | null>(null);
  const [toggling, setToggling] = useState<AppUserRow | null>(null);
  if (!isAdmin) return <Card title="Users & roles (ADM-04)"><p className="text-sm text-slate-600">User and role administration needs the tenant administrator role.</p></Card>;
  return (
    <Card title="Users & roles (ADM-04)">
      <p className="mb-3 text-sm text-slate-600">Role changes are checked against the segregation-of-duties role pairs (e.g. buyer + receiver) and need MFA for
        approver, finance and admin roles. Every change is audited with its reason.</p>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <DataTable<AppUserRow> rows={data ?? []} empty="No users" columns={[
          { key: 'name', header: 'User', render: (u) => <span><span className="font-medium">{u.name}</span><span className="block text-xs text-slate-500">{u.email}</span></span> },
          { key: 'roles', header: 'Roles', render: (u) => <span className="text-xs">{u.roles.map((r) => label(r)).join(', ')}</span> },
          { key: 'supplierUser', header: 'Kind', render: (u) => <span className="text-xs">{u.supplierUser ? 'Supplier (external)' : 'Internal'}</span> },
          { key: 'mfaEnrolled', header: 'MFA', render: (u) => <span className={`text-xs ${u.mfaEnrolled ? 'text-emerald-700' : 'text-slate-500'}`}>{u.mfaEnrolled ? 'Enrolled' : 'Not enrolled'}</span> },
          { key: 'attributes', header: 'Scope', render: (u) => <span className="font-mono text-[11px]">{Object.entries(u.attributes ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(',') : String(v)}`).join(' · ') || '–'}</span> },
          { key: 'active', header: 'Status', render: (u) => <StatusChip status={u.active ? 'ACTIVE' : 'INACTIVE'} /> },
          { key: 'actions', header: '', render: (u) => (
            <div className="flex justify-end gap-2">
              {!u.supplierUser && <Button variant="ghost" onClick={() => setEditing(u)}>Roles</Button>}
              <Button variant={u.active ? 'danger' : 'secondary'} onClick={() => setToggling(u)}>{u.active ? 'Deactivate' : 'Activate'}</Button>
            </div>
          ) },
        ]} />
      )}
      {editing && <RolesDialog user={editing} onClose={() => setEditing(null)} />}
      {toggling && <ActiveDialog user={toggling} onClose={() => setToggling(null)} />}
    </Card>
  );
}

function RolesDialog({ user, onClose }: { user: AppUserRow; onClose: () => void }) {
  const [roles, setRoles] = useState<string[]>(user.roles);
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.put(`/admin/users/${user.id}/roles`, { roles, reason: reason.trim() }), {
    success: `${user.email}: roles updated`, onSuccess: onClose,
  });
  const catalogue = useApi<RoleRow[]>('/admin/roles');
  const internalRoles = (catalogue.data ?? []).map((r) => r.role).filter((r) => r !== 'SUPPLIER_USER');
  const toggle = (r: string) => setRoles((rs) => (rs.includes(r) ? rs.filter((x) => x !== r) : [...rs, r]));
  return (
    <Dialog open title={`Roles · ${user.name}`} onClose={onClose}>
      <div className="space-y-3">
        <fieldset>
          <legend className="text-xs font-medium text-slate-700">Roles</legend>
          <div className="mt-1 grid gap-1.5 sm:grid-cols-3">
            {catalogue.isLoading && <Loading />}
            {internalRoles.map((r) => (
              <label key={r} className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={roles.includes(r)} onChange={() => toggle(r)} />
                {label(r)}{SENSITIVE.includes(r) && <span className="text-[10px] font-semibold uppercase text-amber-700">MFA</span>}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Joined the contracts team, ticket HR-2291" />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!roles.length || reason.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>Save roles</Button>
        </div>
      </div>
    </Dialog>
  );
}

function ActiveDialog({ user, onClose }: { user: AppUserRow; onClose: () => void }) {
  const activate = !user.active;
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.put(`/admin/users/${user.id}/active`, { active: activate, reason: reason.trim() }), {
    success: `${user.email} ${activate ? 'activated' : 'deactivated'}`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`${activate ? 'Activate' : 'Deactivate'} ${user.name}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{activate ? 'The user can sign in again with their existing roles.' : 'The user can no longer sign in. Their history and audit trail are kept.'}</p>
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder={activate ? 'e.g. Returned from leave' : 'e.g. Left the company on 31 Oct'} />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={activate ? 'primary' : 'danger'} disabled={reason.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>{activate ? 'Activate' : 'Deactivate'}</Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- industry templates
type IndustryTemplate = { code: string; name: string; purchaseTypes: string[]; demandSources: string[]; eventTemplates: string[]; contractTemplates: string[];
  receipt: string; match: string; controls: string[]; kpis: string[]; demoCase: string; ruleOverrides: string[]; applied: boolean };

function TemplatesTab() {
  const { data, isLoading, error } = useApi<{ current: string; templates: IndustryTemplate[]; ruleSets: Record<string, string> }>('/admin/templates');
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">Industry packs preconfigure purchase types, sourcing and contract templates, receipt and match rules, controls and KPIs.
        This tenant runs <span className="font-semibold">{data.templates.find((t) => t.applied)?.name ?? label(data.current)}</span>.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        {data.templates.map((t) => (
          <Card key={t.code} className={t.applied ? 'ring-2 ring-[#1A56DB]' : ''}
            title={<span>{t.name} <span className="font-mono text-[11px] text-slate-500">{t.code}</span></span>}
            actions={t.applied ? <StatusChip status="ACTIVE" /> : undefined}>
            <dl className="space-y-2 text-sm">
              {([['Purchase types', t.purchaseTypes.map((x) => label(x)).join(', ')], ['Demand', t.demandSources.join('; ')],
                ['Sourcing', t.eventTemplates.join('; ')], ['Contracts', t.contractTemplates.map((x) => label(x)).join(', ')], ['Receipt', t.receipt],
                ['Match', t.match], ['Controls', t.controls.join('; ')], ['KPIs', t.kpis.join(', ')], ['Demo case', t.demoCase],
                ['Rule overrides', t.ruleOverrides.length ? t.ruleOverrides.map((k) => `${k}${data.ruleSets[k] ? ` @${data.ruleSets[k]}` : ''}`).join(', ') : 'none']] as [string, string][])
                .map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[110px_1fr] gap-2">
                    <dt className="text-xs text-slate-500">{k}</dt><dd className="text-slate-800">{v || '–'}</dd>
                  </div>
                ))}
            </dl>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- page
export default function Admin() {
  const user = useSessionUser();
  const isAdmin = !!user?.roles.includes('TENANT_ADMIN');
  return (
    <div className="space-y-4">
      <PageHeader eyebrow="ADM-01..06 · Administration" title="Administration"
        subtitle="Organisation and currencies, rules and thresholds, users, roles and segregation of duties, ERP integration, the audit trail, operations and industry templates." />
      {user && !isAdmin && (
        <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          You are signed in as {user.roles.map((r) => label(r)).join(', ')}. You can read the organisation, rules, SoD and templates, but FX rates,
          users and roles, changing rules, the integration monitor, the audit explorer and operations need the tenant administrator role (admin@axion.example).
        </p>
      )}
      <Tabs tabs={[
        { id: 'org', label: 'Organisation (ADM-01)', content: <OrganisationTab isAdmin={isAdmin} /> },
        { id: 'rules', label: 'Rules & thresholds', content: <RulesTab /> },
        { id: 'users', label: 'Users & roles (ADM-04)', content: <UsersTab isAdmin={isAdmin} /> },
        { id: 'sod', label: 'Roles & SoD', content: <SodTab /> },
        { id: 'integration', label: 'Integration monitor', content: <IntegrationTab /> },
        { id: 'audit', label: 'Audit explorer', content: <AuditTab /> },
        { id: 'ops', label: 'Operations', content: <OpsTab /> },
        { id: 'templates', label: 'Industry templates', content: <TemplatesTab /> },
      ]} />
    </div>
  );
}
