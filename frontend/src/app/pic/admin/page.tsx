'use client';

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date, dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { useSessionUser } from '../invoices/_components';
import { ConnectorsTab } from './_connectors';
import { ErpSyncTab } from './_sync';
import { DelegationsTab, JobsTab } from './_jobs';
import { SimulationTab } from './_simulation';
import { MandatoryFieldsTab } from './_mandatory';
import { WorkflowTab } from './_designer';
import { MappingsTab } from './_mappings';
import { MitigationReport, MitigationReportData, RuleModeButton } from './_sod';
import { OrganisationTab } from './_org';
import { UsersTab } from './_users';
import { RolesMatrixTab } from './_roles';
import { TemplatesTab } from './_templates';
import { ApprovalMatrixTab } from './_matrix';

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
function SodTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<{ rules: SodRule[]; violations: SodViolation[]; mitigations: MitigationReportData }>('/admin/sod');
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
          { key: 'mode', header: 'Mode', render: (r) => <RuleModeButton code={r.code} mode={r.mode} risk={r.risk} isAdmin={isAdmin} /> },
          { key: 'description', header: 'Description', className: 'min-w-[220px]' },
        ]} />
      </Card>
      {data.mitigations && <MitigationReport data={data.mitigations} isAdmin={isAdmin} />}
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

// ---------------------------------------------------------------- page
export default function Admin() {
  const user = useSessionUser();
  const isAdmin = !!user?.roles.includes('TENANT_ADMIN');
  return (
    <div className="space-y-4">
      <PageHeader kpis="M13" eyebrow="ADM-01..06 · Administration" title="Administration"
        subtitle="Organisation and currencies, rules and thresholds, users, roles and segregation of duties, ERP integration, the audit trail, operations and industry templates." />
      {user && !isAdmin && (
        <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          You are signed in as {user.roles.map((r) => label(r)).join(', ')}. You can read the organisation, rules, SoD and templates, but changing the organisation, FX rates,
          users and roles, rules and templates, the integration monitor, the audit explorer and operations need the tenant administrator role (admin@axion.example).
        </p>
      )}
      <Tabs tabs={[
        { id: 'org', label: 'Organisation (ADM-01)', content: <OrganisationTab isAdmin={isAdmin} /> },
        { id: 'rules', label: 'Rules & thresholds', content: <RulesTab /> },
        { id: 'approvals', label: 'Approval matrix (ADM-03)', content: <ApprovalMatrixTab isAdmin={isAdmin} /> },
        { id: 'simulate', label: 'Approval simulation (ADM-03)', content: <SimulationTab /> },
        { id: 'mandatory', label: 'Mandatory fields', content: <MandatoryFieldsTab /> },
        { id: 'users', label: 'Users & roles (ADM-04)', content: <UsersTab isAdmin={isAdmin} /> },
        { id: 'matrix', label: 'Permission matrix', content: <RolesMatrixTab isAdmin={isAdmin} /> },
        { id: 'sod', label: 'Roles & SoD', content: <SodTab isAdmin={isAdmin} /> },
        { id: 'workflow', label: 'Workflow designer', content: <WorkflowTab /> },
        { id: 'integration', label: 'Integration monitor', content: <IntegrationTab /> },
        { id: 'connectors', label: 'ERP connectors & imports', content: <ConnectorsTab /> },
        { id: 'mappings', label: 'ERP field mappings', content: <MappingsTab /> },
        { id: 'erp-sync', label: 'ERP sync', content: <ErpSyncTab /> },
        { id: 'audit', label: 'Audit explorer', content: <AuditTab /> },
        { id: 'ops', label: 'Operations', content: <OpsTab /> },
        { id: 'jobs', label: 'Jobs', content: <JobsTab /> },
        { id: 'delegations', label: 'Delegations', content: <DelegationsTab /> },
        { id: 'templates', label: 'Industry templates', content: <TemplatesTab isAdmin={isAdmin} /> },
      ]} />
    </div>
  );
}
