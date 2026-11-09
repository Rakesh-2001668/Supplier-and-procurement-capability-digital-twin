'use client';

// ADM-04 user lifecycle: invite (single-use activation link), roles, password-reset link, session revocation, MFA reset,
// deactivate / activate, bulk CSV import with a dry run. Administrators only; the API checks the role again on every call.

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type AppUserRow = { id: string; email: string; name: string; roles: string[]; active: boolean; status: 'ACTIVE' | 'INVITED' | 'INACTIVE'; mfaEnrolled: boolean;
  supplierUser: boolean; attributes: Record<string, unknown> };
// The role catalogue comes from the backend (GET /admin/roles): built-in roles and the tenant's own; assignment re-validates SoD pairs and MFA.
type RoleRow = { role: string; name: string; kind: 'BUILT_IN' | 'CUSTOM'; scopes: string[] };
type Issued = { email: string; activationUrl?: string; resetUrl?: string; expiresAt: string; emailStatus: string };
const SENSITIVE = ['TENANT_ADMIN', 'FINANCE_CONTROLLER', 'CFO', 'CPO'];

function csvList(v: string): string[] {
  return v.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
}

function LinkOnce({ issued, heading }: { issued: Issued; heading: string }) {
  const url = issued.activationUrl ?? issued.resetUrl ?? '';
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" className="space-y-2 rounded-lg border border-emerald-300 bg-emerald-50 p-3">
      <p className="text-sm font-semibold text-emerald-900">{heading}</p>
      <p className="text-xs text-emerald-900">This link is shown once. It works once and expires {dateTime(issued.expiresAt)}.
        E-mail: {issued.emailStatus === 'SENT' ? 'sent to the user' : issued.emailStatus === 'DISABLED' ? 'not sent (no mail server configured); give the link to the user yourself' : 'delivery failed; give the link to the user yourself'}.</p>
      <p className="break-all rounded bg-white px-2 py-1 font-mono text-[11px] text-slate-800">{url}</p>
      <Button onClick={async () => { await navigator.clipboard?.writeText(url); setCopied(true); }}>{copied ? 'Copied' : 'Copy link'}</Button>
    </div>
  );
}

function InviteDialog({ onClose }: { onClose: () => void }) {
  const roles = useApi<RoleRow[]>('/admin/roles');
  const [f, setF] = useState({ email: '', name: '', plants: '', companies: '', limit: '' });
  const [picked, setPicked] = useState<string[]>([]);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const cmd = useCommand((body: Record<string, unknown>) => api.post<Issued>('/admin/users', body), {
    success: (r) => `${r.email} invited`, onSuccess: setIssued,
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const choices = (roles.data ?? []).filter((r) => r.role !== 'SUPPLIER_USER');

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(f.email.trim())) { setInvalid('Enter a valid e-mail address.'); return; }
    if (f.name.trim().length < 2) { setInvalid('Enter the user’s name.'); return; }
    if (!picked.length) { setInvalid('Choose at least one role.'); return; }
    if (f.limit.trim() && (Number.isNaN(Number(f.limit)) || Number(f.limit) < 0)) { setInvalid('The approval limit is an amount in rupees.'); return; }
    setInvalid(null);
    const attributes: Record<string, unknown> = {};
    if (csvList(f.plants).length) attributes.plants = csvList(f.plants);
    if (csvList(f.companies).length) attributes.company_codes = csvList(f.companies);
    if (f.limit.trim()) attributes.value_limit_minor = rupeesToMinor(f.limit.trim());
    cmd.mutate({ email: f.email.trim().toLowerCase(), name: f.name.trim(), roles: picked, attributes });
  }

  return (
    <Dialog open title="Invite a user" onClose={onClose}>
      {issued ? (
        <div className="space-y-3">
          <LinkOnce issued={issued} heading={`Activation link for ${issued.email}`} />
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3" noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="E-mail" required>{(id) => <Input id={id} type="email" value={f.email} onChange={set('email')} />}</Field>
            <Field label="Name" required>{(id) => <Input id={id} value={f.name} onChange={set('name')} />}</Field>
            <Field label="Plants" hint="Codes separated by commas, * for all; empty = no restriction recorded">{(id) => <Input id={id} value={f.plants} onChange={set('plants')} placeholder="P100, P200" />}</Field>
            <Field label="Company codes" hint="Codes, or *">{(id) => <Input id={id} value={f.companies} onChange={set('companies')} placeholder="1000" />}</Field>
            <Field label="Approval value limit (₹)" hint="Empty = no limit">{(id) => <Input id={id} inputMode="decimal" value={f.limit} onChange={set('limit')} placeholder="e.g. 500000" />}</Field>
          </div>
          <fieldset>
            <legend className="text-xs font-medium text-slate-700">Roles (required)</legend>
            <div className="mt-1 grid gap-1.5 sm:grid-cols-3">
              {roles.isLoading && <Loading />}
              {choices.map((r) => (
                <label key={r.role} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="h-4 w-4" checked={picked.includes(r.role)}
                    onChange={() => setPicked((p) => (p.includes(r.role) ? p.filter((x) => x !== r.role) : [...p, r.role]))} />
                  {r.kind === 'CUSTOM' ? r.name : label(r.role)}{r.kind === 'CUSTOM' && <span className="text-[10px] font-semibold uppercase text-slate-500">custom</span>}
                  {SENSITIVE.includes(r.role) && <span className="text-[10px] font-semibold uppercase text-amber-700">MFA</span>}
                </label>
              ))}
            </div>
          </fieldset>
          <p className="text-xs text-slate-600">The user gets a single-use link to choose a password. Role combinations that break segregation of duties are refused.</p>
          {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
          <ProblemBox error={cmd.error} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" busy={cmd.isPending}>Send invitation</Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

type ImportReport = { summary: { rows: number; valid: number; errors: number; created: number; dryRun: boolean };
  report: { row: number; email: string; status: string; errors: string[] }[]; users?: Issued[] };
const SAMPLE = 'email,name,roles,plants,company_codes,value_limit_minor\nnew.buyer@example.com,New Buyer,BUYER,P100,1000,50000000\n';

function ImportDialog({ onClose }: { onClose: () => void }) {
  const [csv, setCsv] = useState(SAMPLE);
  const [result, setResult] = useState<ImportReport | null>(null);
  const run = useCommand((dry: boolean) => api.post<ImportReport>('/admin/users/import', { csv, dry_run: dry }), {
    success: (r) => (r.summary.dryRun ? `Checked ${r.summary.rows} rows: ${r.summary.valid} valid, ${r.summary.errors} with errors` : `${r.summary.created} users invited`),
    onSuccess: setResult,
  });
  const created = result && !result.summary.dryRun && result.summary.created > 0;
  function download() {
    const text = (result?.users ?? []).map((u) => `${u.email},${u.activationUrl}`).join('\n');
    const url = URL.createObjectURL(new Blob([`email,activation_link\n${text}\n`], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'activation-links.csv';
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <Dialog open title="Import users from CSV" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs text-slate-600">Columns: email, name, roles (separate several with ;), plants, company_codes, value_limit_minor (paise). Every row is checked first;
          nothing is created unless all rows are valid.</p>
        <Field label="CSV file">{(id) => <input id={id} type="file" accept=".csv,text/csv" className="text-sm"
          onChange={async (e) => { const file = e.target.files?.[0]; if (file) { setCsv(await file.text()); setResult(null); } }} />}</Field>
        <Field label="CSV content">{(id) => <Textarea id={id} value={csv} onChange={(e) => { setCsv(e.target.value); setResult(null); }} spellCheck={false} className="min-h-[140px] font-mono text-xs" />}</Field>
        <ProblemBox error={run.error} />
        {result && (
          <div className="space-y-2">
            <p role="status" className="text-sm">{result.summary.rows} rows · {result.summary.valid} valid · {result.summary.errors} with errors{result.summary.dryRun ? ' (dry run, nothing created)' : ` · ${result.summary.created} created`}</p>
            <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-xs"><tbody>
                {result.report.map((r) => (
                  <tr key={r.row} className="border-b border-slate-100 last:border-0">
                    <td className="px-2 py-1">row {r.row}</td><td className="px-2 py-1 font-mono">{r.email || '–'}</td>
                    <td className="px-2 py-1"><StatusChip status={r.status === 'OK' ? 'ACTIVE' : 'REJECTED'} /></td>
                    <td className="px-2 py-1 text-red-800">{r.errors.join('; ')}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
            {created && <Button onClick={download}>Download the activation links (shown once)</Button>}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{created ? 'Close' : 'Cancel'}</Button>
          {!created && <Button busy={run.isPending} onClick={() => run.mutate(true)}>Dry run</Button>}
          {!created && <Button variant="primary" busy={run.isPending} disabled={!result || !result.summary.dryRun || result.summary.errors > 0} onClick={() => run.mutate(false)}>Import</Button>}
        </div>
      </div>
    </Dialog>
  );
}

function ReasonDialog({ title, intro, action, danger, onClose, run, success, show }: {
  title: string; intro: string; action: string; danger?: boolean; onClose: () => void; run: (reason: string) => Promise<unknown>; success: string; show?: (r: Issued) => string | null;
}) {
  const [reason, setReason] = useState('');
  const [issued, setIssued] = useState<Issued | null>(null);
  const cmd = useCommand(() => run(reason.trim()), { success, onSuccess: (r) => (show ? setIssued(r as Issued) : onClose()) });
  return (
    <Dialog open title={title} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{intro}</p>
        {issued ? <LinkOnce issued={issued} heading={show?.(issued) ?? 'Link'} /> : (
          <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Ticket IT-4411, identity checked" />}</Field>
        )}
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{issued ? 'Done' : 'Cancel'}</Button>
          {!issued && <Button variant={danger ? 'danger' : 'primary'} disabled={reason.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>{action}</Button>}
        </div>
      </div>
    </Dialog>
  );
}

function RolesDialog({ user, onClose }: { user: AppUserRow; onClose: () => void }) {
  const [roles, setRoles] = useState<string[]>(user.roles);
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.put(`/admin/users/${user.id}/roles`, { roles, reason: reason.trim() }), {
    success: `${user.email}: roles updated`, onSuccess: onClose,
  });
  const catalogue = useApi<RoleRow[]>('/admin/roles');
  const internalRoles = (catalogue.data ?? []).filter((r) => r.role !== 'SUPPLIER_USER');
  const toggle = (r: string) => setRoles((rs) => (rs.includes(r) ? rs.filter((x) => x !== r) : [...rs, r]));
  return (
    <Dialog open title={`Roles · ${user.name}`} onClose={onClose}>
      <div className="space-y-3">
        <fieldset>
          <legend className="text-xs font-medium text-slate-700">Roles</legend>
          <div className="mt-1 grid gap-1.5 sm:grid-cols-3">
            {catalogue.isLoading && <Loading />}
            {internalRoles.map((r) => (
              <label key={r.role} className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={roles.includes(r.role)} onChange={() => toggle(r.role)} />
                {r.kind === 'CUSTOM' ? r.name : label(r.role)}{SENSITIVE.includes(r.role) && <span className="text-[10px] font-semibold uppercase text-amber-700">MFA</span>}
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

type Action = { kind: 'roles' | 'active' | 'mfa' | 'reset' | 'revoke' | 'resend'; user: AppUserRow };

export function UsersTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<AppUserRow[]>(isAdmin ? '/admin/users' : null);
  const [action, setAction] = useState<Action | null>(null);
  const [invite, setInvite] = useState(false);
  const [importing, setImporting] = useState(false);
  const resend = useCommand((u: AppUserRow) => api.post<Issued>(`/admin/users/${u.id}/resend-invitation`), { success: 'New activation link created' });
  const [resent, setResent] = useState<Issued | null>(null);
  if (!isAdmin) return <Card title="Users & roles (ADM-04)"><p className="text-sm text-slate-600">User and role administration needs the tenant administrator role.</p></Card>;
  const close = () => setAction(null);
  const u = action?.user;
  return (
    <Card title="Users & roles (ADM-04)" actions={<div className="flex gap-2"><Button onClick={() => setImporting(true)}>Import CSV</Button><Button variant="primary" onClick={() => setInvite(true)}>Invite user</Button></div>}>
      <p className="mb-3 text-sm text-slate-600">New users get a single-use activation link. Role changes are checked against the segregation-of-duties pairs (e.g. buyer + receiver) and
        need MFA for approver, finance and admin roles. Every change is audited with its reason.</p>
      {resent && <div className="mb-3"><LinkOnce issued={resent} heading={`New activation link for ${resent.email}`} /></div>}
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : (
        <DataTable<AppUserRow> rows={data ?? []} empty="No users" columns={[
          { key: 'name', header: 'User', render: (x) => <span><span className="font-medium">{x.name}</span><span className="block text-xs text-slate-500">{x.email}</span></span> },
          { key: 'roles', header: 'Roles', render: (x) => <span className="text-xs">{x.roles.map((r) => label(r)).join(', ')}</span> },
          { key: 'supplierUser', header: 'Kind', render: (x) => <span className="text-xs">{x.supplierUser ? 'Supplier (external)' : 'Internal'}</span> },
          { key: 'mfaEnrolled', header: 'MFA', render: (x) => <span className={`text-xs ${x.mfaEnrolled ? 'text-emerald-700' : 'text-slate-500'}`}>{x.mfaEnrolled ? 'Enrolled' : 'Not enrolled'}</span> },
          { key: 'attributes', header: 'Scope', render: (x) => <span className="font-mono text-[11px]">{Object.entries(x.attributes ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(',') : String(v)}`).join(' · ') || '–'}</span> },
          { key: 'status', header: 'Status', render: (x) => <StatusChip status={x.status} /> },
          { key: 'actions', header: '', render: (x) => (
            <div className="flex flex-wrap justify-end gap-1">
              {!x.supplierUser && <Button variant="ghost" onClick={() => setAction({ kind: 'roles', user: x })}>Roles</Button>}
              {x.status === 'INVITED' && <Button variant="ghost" busy={resend.isPending} onClick={() => resend.mutate(x, { onSuccess: setResent })}>New link</Button>}
              {!x.supplierUser && x.status === 'ACTIVE' && <Button variant="ghost" onClick={() => setAction({ kind: 'reset', user: x })}>Reset password</Button>}
              {x.status !== 'INVITED' && <Button variant="ghost" onClick={() => setAction({ kind: 'revoke', user: x })}>Revoke sessions</Button>}
              {x.mfaEnrolled && <Button variant="ghost" onClick={() => setAction({ kind: 'mfa', user: x })}>Reset MFA</Button>}
              <Button variant={x.active ? 'danger' : 'secondary'} onClick={() => setAction({ kind: 'active', user: x })}>{x.active ? 'Deactivate' : 'Activate'}</Button>
            </div>
          ) },
        ]} />
      )}
      {invite && <InviteDialog onClose={() => setInvite(false)} />}
      {importing && <ImportDialog onClose={() => setImporting(false)} />}
      {u && action.kind === 'roles' && <RolesDialog user={u} onClose={close} />}
      {u && action.kind === 'active' && (
        <ReasonDialog title={`${u.active ? 'Deactivate' : 'Activate'} ${u.name}`} action={u.active ? 'Deactivate' : 'Activate'} danger={u.active} onClose={close}
          intro={u.active ? 'The user can no longer sign in. Their history and audit trail are kept.' : 'The user can sign in again with their existing roles.'}
          success={`${u.email} ${u.active ? 'deactivated' : 'activated'}`} run={(reason) => api.put(`/admin/users/${u.id}/active`, { active: !u.active, reason })} />
      )}
      {u && action.kind === 'mfa' && (
        <ReasonDialog title={`Reset authenticator · ${u.name}`} action="Reset authenticator" danger onClose={close}
          intro="Removes the user’s authenticator app, for example after a lost phone. If MFA is mandatory for their role they enrol a new one at the next sign-in. Confirm the user’s identity first; you cannot reset your own."
          success={`${u.email}: authenticator removed`} run={(reason) => api.post(`/admin/users/${u.id}/mfa/reset`, { reason })} />
      )}
      {u && action.kind === 'reset' && (
        <ReasonDialog title={`Password reset · ${u.name}`} action="Create reset link" onClose={close} show={(r) => `Reset link for ${r.email}`}
          intro="Creates a single-use link (valid for a few hours) that lets the user choose a new password. Using it ends all of the user’s open sessions. The current password keeps working until then."
          success="Reset link created" run={(reason) => api.post(`/admin/users/${u.id}/password-reset`, { reason })} />
      )}
      {u && action.kind === 'revoke' && (
        <ReasonDialog title={`Revoke sessions · ${u.name}`} action="Revoke sessions" danger onClose={close}
          intro="Every sign-in of this user ends at once: the next request from any browser or device is refused and the user signs in again."
          success={`${u.email}: sessions revoked`} run={(reason) => api.post(`/admin/users/${u.id}/revoke-sessions`, { reason })} />
      )}
    </Card>
  );
}
