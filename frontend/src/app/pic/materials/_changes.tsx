'use client';

// Pending workflows 17 / 18: change requests for an existing material (before/after, owning domains, impact analysis, steward decision),
// the material detail page and its version history.

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ReactNode, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AuditTrail } from '@/components/pic/object';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Input, Loading, PageHeader, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { useToast } from '@/components/pic/toast';
import { api, ApiError, Paged } from '@/lib/pic/api';
import { date, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

export type MaterialRow = {
  id: string; number: string; description: string; type: string; material_group: string | null; category: string | null; base_uom: string;
  valuation_class: string | null; hsn_code: string | null; gst_rate: string | null; mpn: string | null; attributes: Record<string, unknown> | null;
  standard_price_minor: number | null; quality_managed: boolean; mrp_type: string; lot_size_policy: string; lot_size_qty: string | null;
  min_lot: string | null; max_lot: string | null; pack_size: string | null; safety_stock: string; planned_delivery_days: number; gr_processing_days: number;
  status: string; erp_synced: boolean; version: number;
};
type Change = { field: string; label: string; from: unknown; to: unknown; domain: string; alsoApprove: string[]; routed: boolean };
type Impact = {
  openPurchaseOrders: { count: number; lines: { po: string; status: string; line: number; openQty: string; uom: string }[] };
  contracts: { count: number; lines: { contract: string; status: string; line: number }[] };
  catalogueItems: { count: number; items: { supplierPartNo: string; priceMinor: number }[] };
  infoRecords: { count: number; plants: string[] };
  planning: { openPlannedOrders: number; forecastPeriods: number; sourceLists: number; quotaArrangements: number; openRequisitionLines: number; liveSourcingEvents: string[] };
  stockQty: string; blockers: string[]; warnings: string[];
};
type ChangeTask = { id: string; domain: string | null; status: string; decision: string | null; comment: string | null; completedAt: string | null };
export type ChangeRequest = {
  id: string; number: string; material: string | null; materialDescription: string | null; status: string; material_type: string; changes: Change[];
  domains: string[]; impact: Impact; reason: string; requested_by: string; from_version: number; to_version: number | null;
  approvals: { domain: string | null; by: string; decision: string; at: string | null; comment: string | null }[]; rule_set_version: string | null;
  erp_key: string | null; erp_document: string | null; applied_at: string | null; rejection_reason: string | null; created_at: string; tasks: ChangeTask[];
};
type Preview = { material: string; version: number; changes: Change[]; domains: string[]; ruleSet: string; outside: string[]; impact: Impact };
type FieldSpec = { field: string; label: string; kind: string; domain: string; alsoApprove: string[] };
type Ownership = { ruleSet: string; materialType: string; outsideOwnership: 'ROUTE' | 'REFUSE'; fields: FieldSpec[]; domains: string[] };
type Version = { id: string; version: number; snapshot: Record<string, unknown>; changed_fields: string[]; change_request_id: string | null; reason: string | null; valid_from: string };
type VersionsResponse = { material: string; version: number; versions: Version[] };
type Me = { userId: string; roles: string[]; scopes: string[] };
type Task = { id: string; name: string; kind: string; object_ref: string; due_at: string | null };

const newKey = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

/** A value of the material master (or a snapshot of it) as text. */
export function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '–';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length ? entries.map(([k, v]) => `${k}=${String(v)}`).join(', ') : '–';
  }
  return String(value);
}

/** The material master by number: the list API has no detail route, so the pages are read until the number is found. */
export function useMaterial(number: string) {
  return useQuery<MaterialRow, ApiError>({
    queryKey: ['material', number],
    queryFn: async () => {
      let cursor: string | null = null;
      for (let page = 0; page < 40; page++) {
        const result: Paged<MaterialRow> = await api.get<Paged<MaterialRow>>(`/materials?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
        const found = result.items.find((m) => m.number === number);
        if (found) return found;
        if (!result.nextCursor) break;
        cursor = result.nextCursor;
      }
      throw new ApiError({ status: 404, code: 'NOT_FOUND', title: 'NOT_FOUND', detail: `Material ${number} was not found` });
    },
  });
}

// ---------------------------------------------------------------- shared views
export function ChangeTable({ changes }: { changes: Change[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2">Field</th><th className="px-3 py-2">Before</th><th className="px-3 py-2">After</th><th className="px-3 py-2">Approving domain</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {changes.map((c) => (
            <tr key={c.field} className="align-top">
              <td className="px-3 py-2 font-medium">{c.label}<span className="block font-mono text-[11px] text-slate-400">{c.field}</span></td>
              <td className="px-3 py-2 text-slate-600 line-through decoration-slate-300">{show(c.from)}</td>
              <td className="px-3 py-2 font-semibold text-slate-900">{show(c.to)}</td>
              <td className="px-3 py-2">
                {label(c.domain)}{c.alsoApprove.length > 0 && <span className="block text-xs text-slate-500">also {c.alsoApprove.map(label).join(', ')}</span>}
                {c.routed && <span className="block text-xs text-amber-700">routed to the owning steward</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Count({ name, value, hint }: { name: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2">
      <p className="text-xs text-slate-500">{name}</p>
      <p className="text-lg font-semibold tabular-nums text-slate-900">{value}</p>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** Impact analysis: what the change touches (open POs, contracts, catalogues, info records, planning, stock) with blockers and warnings. */
export function ImpactView({ impact }: { impact: Impact }) {
  const planning = impact.planning;
  return (
    <div className="space-y-3">
      {impact.blockers.map((b) => <p key={b} role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900"><span className="font-semibold">Blocked · </span>{b}</p>)}
      {impact.warnings.map((w) => <p key={w} role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{w}</p>)}
      <div className="grid gap-2 sm:grid-cols-3 md:grid-cols-6">
        <Count name="Open purchase orders" value={impact.openPurchaseOrders.count} />
        <Count name="Live contracts" value={impact.contracts.count} />
        <Count name="Catalogue items" value={impact.catalogueItems.count} />
        <Count name="Info records" value={impact.infoRecords.count} hint={impact.infoRecords.plants.join(', ') || undefined} />
        <Count name="Open planned orders" value={planning.openPlannedOrders} hint={`${planning.openRequisitionLines} requisition line(s)`} />
        <Count name="Stock on hand" value={impact.stockQty} />
      </div>
      <p className="text-xs text-slate-500">
        Planning: {planning.forecastPeriods} forecast period(s), {planning.sourceLists} source list entr{planning.sourceLists === 1 ? 'y' : 'ies'}, {planning.quotaArrangements} quota arrangement(s)
        {planning.liveSourcingEvents.length > 0 && <> · live sourcing events {planning.liveSourcingEvents.join(', ')}</>}.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {impact.openPurchaseOrders.lines.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Open purchase order lines</p>
            <ul className="space-y-0.5 text-sm">
              {impact.openPurchaseOrders.lines.slice(0, 8).map((l) => (
                <li key={`${l.po}-${l.line}`}><Link href={`/pic/purchase-orders/${encodeURIComponent(l.po)}`} className="font-medium text-[#1A56DB] hover:underline">{l.po} / {l.line}</Link>{' '}
                  <span className="text-slate-600">{label(l.status)} · open {l.openQty} {l.uom}</span></li>
              ))}
            </ul>
          </div>
        )}
        {impact.contracts.lines.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Contract lines</p>
            <ul className="space-y-0.5 text-sm">
              {impact.contracts.lines.slice(0, 8).map((l) => (
                <li key={`${l.contract}-${l.line}`}><Link href={`/pic/contracts/${encodeURIComponent(l.contract)}`} className="font-medium text-[#1A56DB] hover:underline">{l.contract} / {l.line}</Link>{' '}
                  <span className="text-slate-600">{label(l.status)}</span></li>
              ))}
            </ul>
          </div>
        )}
        {impact.catalogueItems.items.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Catalogue items</p>
            <ul className="space-y-0.5 text-sm">
              {impact.catalogueItems.items.slice(0, 8).map((c) => <li key={c.supplierPartNo}>{c.supplierPartNo} <span className="text-slate-600">{inr(c.priceMinor)}</span></li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- request a change
const BOOLEAN_OPTIONS = [{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }];

function toDraft(value: unknown, kind: string): string {
  if (value === null || value === undefined) return '';
  if (kind === 'dict') return Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k}=${String(v)}`).join('\n');
  return String(value);
}

function parseValue(spec: FieldSpec, text: string): { value?: unknown; error?: string } {
  if (spec.kind === 'dict') {
    const out: Record<string, string> = {};
    for (const raw of text.split('\n').map((l) => l.trim()).filter(Boolean)) {
      const i = raw.indexOf('=');
      if (i <= 0) return { error: `${spec.label}: "${raw}" is not in name=value form` };
      out[raw.slice(0, i).trim()] = raw.slice(i + 1).trim();
    }
    return { value: out };
  }
  if (spec.kind === 'bool') return { value: text === 'true' };
  const numeric = ['int', 'qty', 'days', 'gst'].includes(spec.kind);
  if (numeric && (text.trim() === '' || Number.isNaN(Number(text)))) return { error: `${spec.label} must be a number` };
  return { value: text.trim() };
}

function FieldInput({ spec, id, value, onChange }: { spec: FieldSpec; id: string; value: string; onChange: (v: string) => void }) {
  if (spec.kind === 'bool') return <Select id={id} value={value || 'false'} onChange={(e) => onChange(e.target.value)} options={BOOLEAN_OPTIONS} />;
  if (spec.kind.startsWith('enum:')) {
    return <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} options={spec.kind.slice(5).split(',').map((v) => ({ value: v, label: v }))} />;
  }
  if (spec.kind === 'dict') return <Textarea id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder="name=value, one per line" />;
  const numeric = ['int', 'qty', 'days', 'gst'].includes(spec.kind);
  return <Input id={id} value={value} inputMode={numeric ? 'decimal' : undefined} maxLength={spec.kind.startsWith('text:') ? Number(spec.kind.slice(5)) : undefined}
    onChange={(e) => onChange(e.target.value)} />;
}

export function RequestChangeDialog({ material, onClose }: { material: MaterialRow; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const ownership = useApi<Ownership>(`/material-field-ownership?type=${encodeURIComponent(material.type)}`);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [reason, setReason] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [key, setKey] = useState(newKey);
  const specs = ownership.data?.fields ?? [];
  const current = material as unknown as Record<string, unknown>;

  const touch = () => { setPreview(null); setKey(newKey()); };
  const toggle = (spec: FieldSpec) => {
    touch();
    setDraft((d) => {
      const next = { ...d };
      if (spec.field in next) delete next[spec.field];
      else next[spec.field] = toDraft(current[spec.field], spec.kind);
      return next;
    });
  };
  const setValue = (field: string, value: string) => { touch(); setDraft((d) => ({ ...d, [field]: value })); };

  const parsed = specs.filter((s) => s.field in draft).map((s) => ({ spec: s, ...parseValue(s, draft[s.field]) }));
  const errors = parsed.flatMap((p) => (p.error ? [p.error] : []));
  const changes = Object.fromEntries(parsed.filter((p) => !p.error).map((p) => [p.spec.field, p.value]));
  const ready = parsed.length > 0 && errors.length === 0;
  const reasonOk = reason.trim().length >= 5;

  const run = useMutation<Preview, ApiError, void>({
    mutationFn: () => api.post<Preview>(`/materials/${encodeURIComponent(material.number)}/change-requests/preview`,
      { changes, reason: reasonOk ? reason.trim() : 'Preview of the requested change' }),
    onSuccess: setPreview,
    onError: (e) => toast.problem(e),
  });
  const submit = useCommand(() => api.post<ChangeRequest>(`/materials/${encodeURIComponent(material.number)}/change-requests`,
    { changes, reason: reason.trim() }, { idempotencyKey: key }), {
    success: (r) => `${r.number} sent for approval by ${r.domains.map(label).join(', ')}`,
    onSuccess: (r) => { onClose(); router.push(`/pic/materials/${encodeURIComponent(r.number)}`); },
  });
  const blocked = (preview?.impact.blockers.length ?? 0) > 0;

  return (
    <Dialog open title={`Request change · ${material.number}`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-slate-600">Tick the fields to change. Each owning data-steward domain approves its fields; you cannot approve your own request. The master is updated, versioned and sent to ERP once every domain has approved.</p>
        {ownership.isLoading ? <Loading /> : ownership.error ? <ProblemBox error={ownership.error} /> : (
          <>
            {ownership.data?.outsideOwnership === 'REFUSE' && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">This tenant refuses changes to fields outside your own steward domains; others are rejected when you preview.</p>
            )}
            <ul className="max-h-72 space-y-2 overflow-y-auto pr-1">
              {specs.map((spec) => {
                const on = spec.field in draft;
                return (
                  <li key={spec.field} className={`rounded-lg border p-2 ${on ? 'border-[#1A56DB] bg-blue-50/40' : 'border-slate-200'}`}>
                    <label className="flex items-start gap-2 text-sm">
                      <input type="checkbox" className="mt-1" checked={on} onChange={() => toggle(spec)} />
                      <span className="flex-1">
                        <span className="font-medium">{spec.label}</span>
                        <span className="ml-2 text-xs text-slate-500">{label(spec.domain)} steward{spec.alsoApprove.length ? ` + ${spec.alsoApprove.map(label).join(', ')}` : ''}</span>
                        <span className="block text-xs text-slate-500">Now: {show(current[spec.field])}</span>
                      </span>
                    </label>
                    {on && <div className="mt-2 pl-6"><Field label={`New ${spec.label.toLowerCase()}`}>{(id) => <FieldInput spec={spec} id={id} value={draft[spec.field]} onChange={(v) => setValue(spec.field, v)} />}</Field></div>}
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <Field label="Reason (required)" hint="Recorded with the request, e.g. the ECN or drawing revision">
          {(id) => <Textarea id={id} value={reason} onChange={(e) => { touch(); setReason(e.target.value); }} />}
        </Field>
        {errors.map((e) => <p key={e} role="alert" className="text-xs text-red-700">{e}</p>)}
        <div className="flex justify-end">
          <Button busy={run.isPending} disabled={!ready} onClick={() => run.mutate()}>Preview impact</Button>
        </div>

        {preview && (
          <div className="space-y-3 border-t border-slate-100 pt-3">
            <p className="text-xs text-slate-500">Rule set <span className="font-mono">{preview.ruleSet}</span> · material version {preview.version} · approvals needed from {preview.domains.map(label).join(', ')}</p>
            <ChangeTable changes={preview.changes} />
            {preview.outside.length > 0 && <p className="text-xs text-amber-800">Routed to the owning steward: {preview.outside.join(', ')}.</p>}
            <ImpactView impact={preview.impact} />
          </div>
        )}
        <ProblemBox error={submit.error ?? run.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={submit.isPending} disabled={!preview || blocked || !reasonOk} onClick={() => submit.mutate()}
            title={!reasonOk ? 'Give a reason of at least 5 characters' : blocked ? 'The impact analysis blocks this change' : undefined}>Submit for approval</Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- lists
export function ChangeRequestList({ rows, loading, error }: { rows: ChangeRequest[]; loading?: boolean; error?: ApiError | null }) {
  return (
    <DataTable<ChangeRequest> rows={rows} loading={loading} error={error} rowHref={(r) => `/pic/materials/${encodeURIComponent(r.number)}`} empty="No change requests"
      columns={[
        { key: 'number', header: 'Request' },
        { key: 'material', header: 'Material', render: (r) => <span>{r.material} <span className="text-slate-500">{r.materialDescription}</span></span> },
        { key: 'changes', header: 'Fields', render: (r) => r.changes.map((c) => c.label).join(', ') },
        { key: 'domains', header: 'Domains', render: (r) => r.domains.map(label).join(', ') },
        { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status === 'APPLIED' ? 'COMPLETED' : r.status} /> },
        { key: 'created_at', header: 'Requested', render: (r) => date(r.created_at) },
      ]} />
  );
}

export function AllChangeRequests() {
  const list = useApi<ChangeRequest[]>('/material-change-requests');
  return <ChangeRequestList rows={list.data ?? []} loading={list.isLoading} error={list.error} />;
}

/** Material number → the request waiting for approval, for the pending-changes column of the materials list. */
export function usePendingChanges() {
  const pending = useApi<ChangeRequest[]>('/material-change-requests?status=IN_APPROVAL');
  return Object.fromEntries((pending.data ?? []).map((r) => [r.material ?? '', r.number]));
}

// ---------------------------------------------------------------- material detail
export function MaterialDetail({ number }: { number: string }) {
  const material = useMaterial(number);
  const me = useApi<Me>('/me');
  const changes = useApi<ChangeRequest[]>(`/materials/${encodeURIComponent(number)}/change-requests`);
  const versions = useApi<VersionsResponse>(`/materials/${encodeURIComponent(number)}/versions`);
  const [open, setOpen] = useState(false);
  const m = material.data;
  if (material.isLoading) return <Loading />;
  if (material.error || !m) return <ProblemBox error={material.error} />;
  const pending = (changes.data ?? []).find((c) => c.status === 'IN_APPROVAL');
  const canRequest = !!me.data && (me.data.scopes.includes('mdm:request') || me.data.scopes.includes('req:create')) && m.status === 'ACTIVE';
  const requestNumbers = Object.fromEntries((changes.data ?? []).map((c) => [c.id, c.number]));

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="M03 · Material master (change requests: MDM-02 steward workbench)" title={<>{m.number} <span className="text-base font-normal text-slate-500">{m.description}</span></>}
        subtitle={<span className="inline-flex items-center gap-2"><StatusChip status={m.status} /> version {m.version} · {m.erp_synced ? 'in sync with ERP' : 'ERP update pending'}</span>}
        actions={<>
          <Link href="/pic/materials" className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50">Back to materials</Link>
          {canRequest && <Button variant="primary" disabled={!!pending} title={pending ? `${pending.number} is still in approval` : undefined} onClick={() => setOpen(true)}>Request change</Button>}
        </>} />
      {pending && (
        <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <Link className="font-semibold underline" href={`/pic/materials/${encodeURIComponent(pending.number)}`}>{pending.number}</Link> is waiting for approval by {pending.domains.map(label).join(', ')}
          {' '}({pending.changes.map((c) => c.label).join(', ')}).
        </div>
      )}
      <Card>
        <Tabs tabs={[
          { id: 'master', label: 'Master data', content: (
            <Facts items={[
              ['Type', label(m.type)], ['Material group', m.material_group], ['Category', m.category], ['Base UoM', m.base_uom], ['HSN / SAC', m.hsn_code],
              ['GST rate', m.gst_rate ? `${m.gst_rate}%` : '–'], ['Valuation class', m.valuation_class], ['MPN', m.mpn],
              ['Standard price', m.standard_price_minor != null ? inr(m.standard_price_minor) : '–'], ['Quality managed', show(m.quality_managed)],
              ['MRP type', m.mrp_type], ['Lot-size policy', m.lot_size_policy], ['Fixed lot', show(m.lot_size_qty)], ['Min / max lot', `${show(m.min_lot)} / ${show(m.max_lot)}`],
              ['Pack size', show(m.pack_size)], ['Safety stock', show(m.safety_stock)], ['Planned delivery days', m.planned_delivery_days],
              ['GR processing days', m.gr_processing_days], ['Attributes', show(m.attributes)],
            ]} />
          ) },
          { id: 'changes', label: `Change requests (${changes.data?.length ?? 0})`, content: <ChangeRequestList rows={changes.data ?? []} loading={changes.isLoading} error={changes.error} /> },
          { id: 'versions', label: `Version history (v${m.version})`, content: <VersionHistory data={versions.data} loading={versions.isLoading} error={versions.error} requestNumbers={requestNumbers} /> },
          { id: 'audit', label: 'Audit', content: <AuditTrail type="MATERIAL" objectRef={m.number} /> },
        ]} />
      </Card>
      {open && <RequestChangeDialog material={m} onClose={() => setOpen(false)} />}
    </div>
  );
}

function VersionHistory({ data, loading, error, requestNumbers }: { data?: VersionsResponse; loading: boolean; error: ApiError | null; requestNumbers: Record<string, string> }) {
  if (loading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  const versions = data?.versions ?? [];
  if (!versions.length) return <Empty title="No history yet" hint="A version is recorded when the first change request is raised or applied." />;
  return (
    <ol className="space-y-3">
      {versions.map((v, i) => {
        const older = versions[i + 1];
        return (
          <li key={v.id} className="rounded-lg border border-slate-200 p-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="rounded bg-[#0B1020] px-2 py-0.5 font-mono text-xs text-white">v{v.version}</span>
              <span className="text-slate-600">{dateTime(v.valid_from)}</span>
              {v.change_request_id && requestNumbers[v.change_request_id] && (
                <Link className="font-medium text-[#1A56DB] hover:underline" href={`/pic/materials/${encodeURIComponent(requestNumbers[v.change_request_id])}`}>{requestNumbers[v.change_request_id]}</Link>
              )}
              {v.reason && <span className="text-slate-700">· {v.reason}</span>}
            </div>
            {v.changed_fields.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-sm">
                {v.changed_fields.map((f) => (
                  <li key={f}><span className="font-mono text-xs text-slate-500">{f}</span>{' '}
                    {older ? <><span className="text-slate-500 line-through">{show(older.snapshot[f])}</span> → </> : null}<span className="font-semibold">{show(v.snapshot[f])}</span></li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------- change request detail with the steward decision
export function ChangeRequestDetail({ number }: { number: string }) {
  const { data: r, isLoading, error } = useApi<ChangeRequest>(`/material-change-requests/${encodeURIComponent(number)}`);
  const tasks = useApi<Task[]>('/tasks');
  const me = useApi<Me>('/me');
  const [comment, setComment] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const decide = useCommand((decision: 'APPROVE' | 'REJECT') => api.post<ChangeRequest>(`/material-change-requests/${encodeURIComponent(number)}/decision`,
    { decision, comment: comment.trim() || undefined }), { success: (x) => (x.status === 'APPLIED' ? `${x.number} applied – material version ${x.to_version}` : 'Decision recorded'),
    onSuccess: () => setComment('') });
  if (isLoading) return <Loading />;
  if (error || !r) return <ProblemBox error={error} />;
  const myTask = (tasks.data ?? []).find((t) => t.kind === 'MATERIAL_CHANGE' && t.object_ref === r.number);
  const canCancel = r.status === 'IN_APPROVAL' && !!me.data && (me.data.userId === r.requested_by || me.data.roles.includes('TENANT_ADMIN'));

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="MDM-02 · Steward workbench · Material change request" title={<>{r.number} <span className="text-base font-normal text-slate-500">{r.material} {r.materialDescription}</span></>}
        subtitle={<span className="inline-flex items-center gap-2"><StatusChip status={r.status === 'APPLIED' ? 'COMPLETED' : r.status} />
          {r.status === 'APPLIED' ? `material now at version ${r.to_version}` : `requested on version ${r.from_version}`}</span>}
        actions={<>
          {r.material && <Link href={`/pic/materials/${encodeURIComponent(r.material)}`} className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50">Open material</Link>}
          {canCancel && <Button variant="danger" onClick={() => setCancelling(true)}>Withdraw</Button>}
        </>} />

      {myTask && r.status === 'IN_APPROVAL' && (
        <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-4">
          <p className="text-sm font-semibold">{myTask.name}</p>
          <p className="text-xs text-slate-600">Steward decision for your domain, due {dateTime(myTask.due_at)}. The requester cannot approve, and each domain approval must come from a different person.</p>
          <div className="mt-3 flex flex-col gap-2 md:flex-row md:items-end">
            <div className="md:flex-1"><Field label="Comment (required to reject)">{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field></div>
            <div className="flex gap-2">
              <Button variant="primary" busy={decide.isPending} onClick={() => decide.mutate('APPROVE')}>Approve</Button>
              <Button variant="danger" busy={decide.isPending} disabled={!comment.trim()} onClick={() => decide.mutate('REJECT')}>Reject</Button>
            </div>
          </div>
        </div>
      )}

      {r.rejection_reason && (
        <p role="status" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"><span className="font-semibold">{r.status === 'CANCELLED' ? 'Withdrawn' : 'Not applied'} · </span>{r.rejection_reason}</p>
      )}

      <Card title="Requested change">
        <p className="mb-3 text-sm text-slate-700">{r.reason}</p>
        <ChangeTable changes={r.changes} />
        <div className="mt-4"><Facts items={[
          ['Material type', label(r.material_type)], ['Domains', r.domains.map(label).join(', ')], ['Rule set', <span key="r" className="font-mono text-xs">{r.rule_set_version}</span>],
          ['Requested', dateTime(r.created_at)], ['Applied', dateTime(r.applied_at)], ['ERP key', <span key="k" className="font-mono text-xs">{r.erp_key ?? '–'}</span>],
          ['ERP document', r.erp_document ?? (r.status === 'APPLIED' ? 'posting…' : '–')],
        ]} /></div>
      </Card>

      <Card>
        <Tabs tabs={[
          { id: 'approvals', label: 'Approvals by domain', content: (
            <DataTable<ChangeTask> rows={r.tasks} empty="No approval tasks" columns={[
              { key: 'domain', header: 'Domain', render: (t) => label(t.domain) },
              { key: 'status', header: 'Task', render: (t) => <StatusChip status={t.status === 'COMPLETED' ? 'COMPLETED' : t.status} /> },
              { key: 'decision', header: 'Decision', render: (t) => (t.decision ? label(t.decision) : '–') },
              { key: 'comment', header: 'Comment', render: (t) => t.comment ?? '–' },
              { key: 'completedAt', header: 'When', render: (t) => dateTime(t.completedAt) },
            ]} />
          ) },
          { id: 'impact', label: 'Impact analysis', content: <ImpactView impact={r.impact} /> },
          { id: 'audit', label: 'Audit', content: <AuditTrail type="MATERIAL_CHANGE_REQUEST" objectRef={r.number} /> },
        ]} />
      </Card>
      {cancelling && <WithdrawDialog request={r} onClose={() => setCancelling(false)} />}
    </div>
  );
}

function WithdrawDialog({ request, onClose }: { request: ChangeRequest; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cancel = useCommand(() => api.post<ChangeRequest>(`/material-change-requests/${encodeURIComponent(request.number)}/cancel`, { reason: reason.trim() }),
    { success: `${request.number} withdrawn`, onSuccess: onClose });
  return (
    <Dialog open title={`Withdraw ${request.number}`} onClose={onClose}>
      <Field label="Reason">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="mt-3"><ProblemBox error={cancel.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Keep request</Button>
        <Button variant="danger" busy={cancel.isPending} onClick={() => cancel.mutate()}>Withdraw</Button>
      </div>
    </Dialog>
  );
}
