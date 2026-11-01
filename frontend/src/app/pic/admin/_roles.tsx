'use client';

// ADM-04 roles: the permission matrix (scopes by role), built-in roles read-only, tenant-defined roles with the SoD impact shown
// before saving. A role that would let one person span a segregation-of-duties pair cannot be saved.

import { useEffect, useState } from 'react';
import { Button, Card, Dialog, Field, Input, Loading, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type MatrixRole = { code: string; name: string; description: string | null; kind: 'BUILT_IN' | 'CUSTOM'; scopes: string[]; active: boolean;
  version: number | null; holders: number | null; id: string | null };
type Matrix = { scopes: { scope: string; description: string | null; assignable: boolean; platformLevel: boolean }[]; roles: MatrixRole[];
  sodPairs: { rule: string; description: string; sideA: string[]; sideB: string[] }[] };
type Impact = { allowed: boolean; reason: string | null; added: string[]; removed: string[]; holders: number;
  ownConflicts: { rule: string; description: string; sideA: string[]; sideB: string[] }[];
  affectedUsers: { userId: string; email: string; newConflicts: { rule: string; description: string }[] }[] };

function ImpactPanel({ impact, error }: { impact: Impact | null; error: ApiError | null }) {
  if (error) return <ProblemBox error={error} />;
  if (!impact) return <p className="text-xs text-slate-500">Choose scopes to see the segregation-of-duties impact.</p>;
  return (
    <div role="status" className={`space-y-1 rounded-lg border px-3 py-2 text-sm ${impact.allowed ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-red-200 bg-red-50 text-red-900'}`}>
      <p className="font-semibold">{impact.allowed ? 'No segregation-of-duties conflict' : 'Refused: segregation-of-duties conflict'}</p>
      {impact.ownConflicts.map((c) => <p key={c.rule} className="text-xs">{c.rule}: {c.description}. The role would hold {c.sideA.join(', ')} together with {c.sideB.join(', ')}.</p>)}
      {impact.affectedUsers.filter((u) => u.newConflicts.length).map((u) => (
        <p key={u.userId} className="text-xs">{u.email} would span {u.newConflicts.map((c) => `${c.rule} (${c.description})`).join('; ')}.</p>
      ))}
      <p className="text-xs">{impact.holders} user(s) hold this role{impact.holders > 0 ? '; they are signed out when the scopes change, so the new scopes apply at their next sign-in' : ''}.
        {impact.added.length > 0 && ` Adds: ${impact.added.join(', ')}.`}{impact.removed.length > 0 && ` Removes: ${impact.removed.join(', ')}.`}</p>
    </div>
  );
}

function RoleDialog({ matrix, role, onClose }: { matrix: Matrix; role: MatrixRole | null; onClose: () => void }) {
  const [code, setCode] = useState(role?.code ?? '');
  const [name, setName] = useState(role?.name ?? '');
  const [description, setDescription] = useState(role?.description ?? '');
  const [scopes, setScopes] = useState<string[]>(role?.scopes ?? ['pic:read']);
  const [reason, setReason] = useState('');
  const [impact, setImpact] = useState<Impact | null>(null);
  const [impactError, setImpactError] = useState<ApiError | null>(null);
  const assignable = matrix.scopes.filter((s) => s.assignable);

  useEffect(() => {
    const normalised = code.trim().toUpperCase();
    let cancelled = false;
    const timer = setTimeout(async () => {
      if (normalised.length < 3 || !scopes.length) { setImpact(null); setImpactError(null); return; }
      try {
        const result = await api.post<Impact>('/admin/roles/preview', { code: normalised, scopes }, { idempotencyKey: false });
        if (!cancelled) { setImpact(result); setImpactError(null); }
      } catch (e) {
        if (!cancelled) { setImpact(null); setImpactError(e as ApiError); }
      }
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [code, scopes]);

  const save = useCommand(() => role
    ? api.put(`/admin/roles/${role.id}`, { name: name.trim(), description: description.trim(), scopes, reason: reason.trim() || undefined }, { ifMatch: `"${role.version}"` })
    : api.post('/admin/roles', { code: code.trim().toUpperCase(), name: name.trim(), description: description.trim() || undefined, scopes }), {
    success: role ? `Role ${role.code} saved` : 'Role created', onSuccess: onClose,
  });
  const toggle = (s: string) => setScopes((x) => (x.includes(s) ? x.filter((v) => v !== s) : [...x, s]));
  const ready = name.trim().length >= 2 && code.trim().length >= 3 && scopes.length > 0 && (impact?.allowed ?? false);

  return (
    <Dialog open title={role ? `Edit role ${role.code}` : 'New role'} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Role code" required hint="Capital letters, digits, underscores; cannot change later">{(id) => <Input id={id} value={code} disabled={!!role} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="e.g. GR_DESK" />}</Field>
          <Field label="Name" required>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        </div>
        <Field label="Description">{(id) => <Input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <fieldset>
          <legend className="text-xs font-medium text-slate-700">Scopes (platform-level administration scopes are not available to custom roles)</legend>
          <div className="mt-1 grid max-h-56 gap-1 overflow-y-auto rounded-lg border border-slate-200 p-2 sm:grid-cols-2">
            {assignable.map((s) => (
              <label key={s.scope} className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-0.5 h-4 w-4" checked={scopes.includes(s.scope)} onChange={() => toggle(s.scope)} />
                <span><span className="font-mono text-xs">{s.scope}</span><span className="block text-xs text-slate-500">{s.description}</span></span>
              </label>
            ))}
          </div>
        </fieldset>
        <ImpactPanel impact={impact} error={impactError} />
        {role && <Field label="Reason (optional)">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>}
        <ProblemBox error={save.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!ready} busy={save.isPending} onClick={() => save.mutate()}>{role ? 'Save role' : 'Create role'}</Button>
        </div>
      </div>
    </Dialog>
  );
}

function CustomRoleActions({ role, onEdit }: { role: MatrixRole; onEdit: () => void }) {
  const toggle = useCommand(() => api.post(`/admin/roles/${role.id}/${role.active ? 'deactivate' : 'activate'}`, { reason: 'Changed in administration' }), {
    success: `Role ${role.code} ${role.active ? 'deactivated' : 'activated'}`,
  });
  const remove = useCommand(() => api.delete<{ outcome: string }>(`/admin/roles/${role.id}`), {
    success: (r) => (r.outcome === 'DELETED' ? `Role ${role.code} deleted` : `Role ${role.code} is in use and was deactivated instead`),
  });
  return (
    <div className="flex flex-wrap gap-1">
      <Button variant="ghost" onClick={onEdit}>Edit</Button>
      <Button variant="ghost" busy={toggle.isPending} onClick={() => toggle.mutate()}>{role.active ? 'Deactivate' : 'Activate'}</Button>
      <Button variant="ghost" busy={remove.isPending} onClick={() => remove.mutate()}>Remove</Button>
      <ProblemBox error={toggle.error ?? remove.error} />
    </div>
  );
}

export function RolesMatrixTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<Matrix>('/admin/roles/matrix');
  const [dialog, setDialog] = useState<{ role: MatrixRole | null } | null>(null);
  const [only, setOnly] = useState<'ALL' | 'CUSTOM'>('ALL');
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  const roles = data.roles.filter((r) => r.kind === 'CUSTOM' || (only === 'ALL' && r.code !== 'SUPPLIER_USER'));
  const custom = data.roles.filter((r) => r.kind === 'CUSTOM');
  return (
    <div className="space-y-4">
      <Card title="Permission matrix (ADM-04)" actions={isAdmin ? <Button variant="primary" onClick={() => setDialog({ role: null })}>New custom role</Button> : undefined}>
        <p className="mb-3 text-sm text-slate-600">Scopes by role. Built-in roles are fixed. Tenant-defined roles can hold any scope marked assignable, never a platform-level
          administration scope, and are refused when they would let one person span a segregation-of-duties pair. {!isAdmin && 'Changing roles needs the tenant administrator role.'}</p>
        <div className="mb-2 flex items-center gap-2 text-sm">
          <label className="flex items-center gap-1"><input type="radio" name="rolefilter" checked={only === 'ALL'} onChange={() => setOnly('ALL')} /> All roles</label>
          <label className="flex items-center gap-1"><input type="radio" name="rolefilter" checked={only === 'CUSTOM'} onChange={() => setOnly('CUSTOM')} /> Custom roles only</label>
        </div>
        <div className="max-h-[560px] overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full border-collapse text-xs">
            <caption className="sr-only">Scopes granted by each role</caption>
            <thead className="sticky top-0 z-10 bg-slate-50">
              <tr>
                <th scope="col" className="sticky left-0 z-20 min-w-[220px] bg-slate-50 px-3 py-2 text-left font-semibold uppercase tracking-wide text-slate-500">Scope</th>
                {roles.map((r) => (
                  <th key={r.code} scope="col" className="min-w-[88px] px-2 py-2 text-center font-semibold text-slate-600">
                    <span className="block break-words">{r.kind === 'CUSTOM' ? r.name : label(r.code)}</span>
                    {r.kind === 'CUSTOM' && <span className="text-[10px] font-normal uppercase text-[#1A56DB]">custom{!r.active && ' · inactive'}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.scopes.map((s) => (
                <tr key={s.scope} className="border-t border-slate-100">
                  <th scope="row" className="sticky left-0 bg-white px-3 py-1.5 text-left font-normal">
                    <span className="font-mono">{s.scope}</span>{s.platformLevel && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-semibold uppercase text-amber-800">platform</span>}
                    {s.description && <span className="block text-[11px] text-slate-500">{s.description}</span>}
                  </th>
                  {roles.map((r) => (
                    <td key={r.code} className="px-2 py-1.5 text-center">
                      {r.scopes.includes(s.scope) ? <span aria-label="granted" className={r.active ? 'text-emerald-700' : 'text-slate-400'}>●</span> : <span aria-label="not granted" className="text-slate-200">·</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title={`Custom roles (${custom.length})`}>
        {custom.length === 0 ? <p className="text-sm text-slate-600">No custom roles yet. Built-in roles cover the blueprint; add one when a team needs a different combination of scopes.</p> : (
          <ul className="divide-y divide-slate-100">
            {custom.map((r) => (
              <li key={r.code} className="flex flex-wrap items-start justify-between gap-3 py-2">
                <div>
                  <p className="text-sm font-medium">{r.name} <span className="font-mono text-xs text-slate-500">{r.code}</span> <StatusChip status={r.active ? 'ACTIVE' : 'INACTIVE'} /></p>
                  {r.description && <p className="text-xs text-slate-600">{r.description}</p>}
                  <p className="text-xs text-slate-500">{r.scopes.length} scopes · {r.holders ?? 0} user(s)</p>
                </div>
                {isAdmin && <CustomRoleActions role={r} onEdit={() => setDialog({ role: r })} />}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Segregation-of-duties scope pairs">
        <ul className="space-y-1 text-sm">
          {data.sodPairs.map((p) => <li key={p.rule}><span className="font-mono text-xs font-semibold">{p.rule}</span> {p.description}: <span className="font-mono text-xs">{p.sideA.join(', ')}</span> with <span className="font-mono text-xs">{p.sideB.join(', ')}</span></li>)}
        </ul>
      </Card>
      {dialog && <RoleDialog matrix={data} role={dialog.role} onClose={() => setDialog(null)} />}
    </div>
  );
}
