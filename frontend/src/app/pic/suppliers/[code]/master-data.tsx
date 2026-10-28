'use client';

import { useState } from 'react';
import { TaskPanel } from '@/components/pic/object';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Input, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { emailValid, gstinProblems, panValid, phoneValid, pinValid, STATES } from '../../register/tax';

// MDM-04 supplier tax-ID / address / contact changes (dual approval, masked values) and M04 punch-out configuration.

export type Address = { line1?: string; line2?: string | null; city?: string; state_code?: string; pin?: string; country?: string; phone?: string };
export type PunchoutConfig = { protocol?: string; url?: string; identity?: string; configuredAt?: string; configuredBy?: string };
export type SupplierLite = { code: string; legal_name: string; gstin_masked: string | null; state_code: string | null; contact_email: string | null;
  address: Address | null; punchout: PunchoutConfig | null; status: string };
type ChangeTask = { id: string; role: string; status: string; decision: string | null; completedAt: string | null; comment: string | null };
type MasterChange = { id: string; number: string; field_group: 'TAX' | 'ADDRESS' | 'CONTACT'; status: string; reason: string;
  before_masked: Record<string, unknown>; after_masked: Record<string, unknown>; created_at: string; applied_at: string | null; tasks: ChangeTask[] };

const GROUPS = { TAX: 'Tax IDs (GSTIN / PAN)', ADDRESS: 'Registered address', CONTACT: 'Contact e-mail / phone' } as const;
type Group = keyof typeof GROUPS;

function flatten(values: Record<string, unknown> | null | undefined): [string, string][] {
  const out: [string, string][] = [];
  for (const [k, v] of Object.entries(values ?? {})) {
    if (v === null || v === undefined || v === '') continue;
    if (typeof v === 'object') out.push(...flatten(v as Record<string, unknown>).map(([kk, vv]) => [`${k}.${kk}`, vv] as [string, string]));
    else out.push([k, String(v)]);
  }
  return out;
}

function MaskedValues({ values }: { values: Record<string, unknown> }) {
  const entries = flatten(values);
  if (!entries.length) return <span className="text-slate-400">–</span>;
  return (
    <dl className="space-y-0.5 text-xs">
      {entries.map(([k, v]) => <div key={k}><dt className="inline text-slate-500">{label(k.replace('.', ' '))}: </dt><dd className="inline font-mono">{v}</dd></div>)}
    </dl>
  );
}

function addressText(a: Address | null | undefined) {
  if (!a || !a.line1) return '–';
  return [a.line1, a.line2, a.city, a.pin, a.state_code, a.country].filter(Boolean).join(', ');
}

/** ``portal``: the supplier's own users request changes from the portal; internal approval tasks are not shown to them. */
export function MasterDataCard({ supplier, manager, portal = false }: { supplier: SupplierLite; manager: boolean; portal?: boolean }) {
  const path = `/suppliers/${encodeURIComponent(supplier.code)}/master-changes`;
  const { data, isLoading, error } = useApi<MasterChange[]>(path);
  const [group, setGroup] = useState<Group | null>(null);
  const open = (data ?? []).filter((c) => c.status === 'IN_APPROVAL');
  const pending = (g: Group) => open.some((c) => c.field_group === g);

  return (
    <Card title="Master data changes (MDM-04)" actions={manager && supplier.status !== 'BLOCKED' ? (
      <>{(Object.keys(GROUPS) as Group[]).map((g) => (
        <Button key={g} disabled={pending(g)} title={pending(g) ? 'A change for this data is already in approval' : undefined} onClick={() => setGroup(g)}>
          Change {g === 'TAX' ? 'tax IDs' : g.toLowerCase()}
        </Button>
      ))}</>
    ) : undefined}>
      <Facts items={[
        ['GSTIN', <span key="g" className="font-mono">{supplier.gstin_masked ?? '–'}</span>],
        ['State code', supplier.state_code ?? '–'],
        ['Registered address', addressText(supplier.address)],
        ['Contact', [supplier.contact_email, supplier.address?.phone].filter(Boolean).join(' · ') || '–'],
      ]} />
      <p className="mt-3 text-xs text-slate-500">Changes need approval by finance and the supplier manager – never by the requester – before they apply.
        New values are stored encrypted; only masked values are shown and audited. Tax-ID changes re-run duplicate and sanctions screening; the ERP supplier master is updated after approval.</p>
      {!portal && open.length > 0 && <div className="mt-4 space-y-3">{open.map((c) => <TaskPanel key={c.id} objectRef={c.number} />)}</div>}
      <div className="mt-4">
        {error ? <ProblemBox error={error} /> : !isLoading && !data?.length ? <Empty title="No master data changes" /> : (
          <DataTable<MasterChange> rows={data ?? []} loading={isLoading} columns={[
            { key: 'number', header: 'Request', render: (c) => <span className="font-mono text-xs">{c.number}</span> },
            { key: 'field_group', header: 'Data', render: (c) => GROUPS[c.field_group] ?? c.field_group },
            { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
            { key: 'before_masked', header: 'Before', render: (c) => <MaskedValues values={c.before_masked} /> },
            { key: 'after_masked', header: 'After', render: (c) => <MaskedValues values={c.after_masked} /> },
            { key: 'tasks', header: 'Approvals', render: (c) => (
              <ul className="space-y-0.5 text-xs">
                {c.tasks.map((t) => (
                  <li key={t.id}>{label(t.role)}: <span className={t.decision === 'REJECT' ? 'font-semibold text-red-700' : t.decision === 'APPROVE' ? 'text-emerald-700' : 'text-amber-700'}>
                    {t.decision ? label(t.decision) : label(t.status)}</span>{t.comment ? ` – ${t.comment}` : ''}</li>
                ))}
              </ul>
            ) },
            { key: 'reason', header: 'Reason', render: (c) => <span className="text-xs">{c.reason}</span> },
            { key: 'created_at', header: 'Requested', render: (c) => <span className="text-xs">{dateTime(c.created_at)}{c.applied_at ? ` · applied ${dateTime(c.applied_at)}` : ''}</span> },
          ]} />
        )}
      </div>
      {group && <MasterChangeDialog supplier={supplier} group={group} onClose={() => setGroup(null)} />}
    </Card>
  );
}

function MasterChangeDialog({ supplier, group, onClose }: { supplier: SupplierLite; group: Group; onClose: () => void }) {
  const current = supplier.address ?? {};
  const [gstin, setGstin] = useState('');
  const [pan, setPan] = useState('');
  const [moveAddress, setMoveAddress] = useState(false);
  const [line1, setLine1] = useState(current.line1 ?? '');
  const [line2, setLine2] = useState(current.line2 ?? '');
  const [city, setCity] = useState(current.city ?? '');
  const [stateCode, setStateCode] = useState(current.state_code ?? supplier.state_code ?? '');
  const [pin, setPin] = useState(current.pin ?? '');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [reason, setReason] = useState('');
  const [problems, setProblems] = useState<string[]>([]);

  const g = gstin.trim().toUpperCase();
  const effectivePan = pan || (g.length >= 12 ? g.slice(2, 12) : '');
  const address = { line1: line1.trim(), line2: line2.trim() || undefined, city: city.trim(), state_code: stateCode, pin: pin.trim(), country: 'IN' };
  const values = group === 'TAX'
    ? { gstin: g, pan: effectivePan, ...(moveAddress ? { address: { ...address, state_code: g.slice(0, 2) } } : {}) }
    : group === 'ADDRESS' ? address
      : { ...(email.trim() ? { email: email.trim() } : {}), ...(phone.trim() ? { phone: phone.trim() } : {}) };
  const submit = useCommand(() => api.post<MasterChange>(`/suppliers/${encodeURIComponent(supplier.code)}/master-changes`, {
    fieldGroup: group, values, reason: reason.trim(),
  }), { success: (c) => `${c.number} sent for dual approval`, onSuccess: onClose });

  const addressProblems = (a: typeof address) => [
    ...(!a.line1 || !a.city ? ['Address line 1 and city are required.'] : []),
    ...(!pinValid(a.pin) ? ['PIN code must be 6 digits.'] : []),
  ];
  const validate = () => {
    const out: string[] = [];
    if (group === 'TAX') {
      const state = moveAddress ? undefined : (current.state_code || undefined);
      out.push(...gstinProblems(g, effectivePan, state));
      if (!panValid(effectivePan)) out.push('PAN must be 5 letters, 4 digits and a letter.');
      if (moveAddress) out.push(...addressProblems(address));
    } else if (group === 'ADDRESS') {
      out.push(...addressProblems(address));
      if (supplier.state_code && stateCode !== supplier.state_code) {
        out.push(`The GSTIN is registered in state ${supplier.state_code}. A move to another state needs a tax-ID change with the new GSTIN and address.`);
      }
    } else {
      if (!email.trim() && !phone.trim()) out.push('Give a new e-mail and/or phone number.');
      if (email.trim() && !emailValid(email)) out.push('E-mail address is not valid.');
      if (phone.trim() && !phoneValid(phone)) out.push('Phone must be 9–18 digits, optionally starting with +.');
    }
    if (reason.trim().length < 3) out.push('Give the reason and the supporting document (e.g. GST amendment order).');
    return out;
  };
  const go = () => {
    const v = validate();
    setProblems(v);
    if (!v.length) submit.mutate();
  };

  const addressFields = (lockedState?: string) => (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="md:col-span-2"><Field label="Address line 1 *">{(id) => <Input id={id} value={line1} onChange={(e) => setLine1(e.target.value)} />}</Field></div>
      <div className="md:col-span-2"><Field label="Address line 2">{(id) => <Input id={id} value={line2} onChange={(e) => setLine2(e.target.value)} />}</Field></div>
      <Field label="City *">{(id) => <Input id={id} value={city} onChange={(e) => setCity(e.target.value)} />}</Field>
      <Field label="PIN code *">{(id) => <Input id={id} value={pin} inputMode="numeric" maxLength={6} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} />}</Field>
      <Field label="State" hint={lockedState ? 'Follows the GSTIN state code' : undefined}>{(id) => (
        <Select id={id} value={lockedState ?? stateCode} disabled={!!lockedState} onChange={(e) => setStateCode(e.target.value)}
          options={[{ value: '', label: 'Choose…' }, ...STATES.map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }))]} />
      )}</Field>
    </div>
  );

  return (
    <Dialog open title={`${GROUPS[group]} – ${supplier.code}`} onClose={onClose}>
      <div className="space-y-3">
        {group === 'TAX' && (
          <>
            <p className="text-sm text-slate-600">Current GSTIN <span className="font-mono">{supplier.gstin_masked ?? '–'}</span> (state {supplier.state_code ?? '–'}).</p>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="New GSTIN *">{(id) => <Input id={id} value={gstin} maxLength={15} className="font-mono" onChange={(e) => setGstin(e.target.value.toUpperCase().replace(/\s/g, ''))} />}</Field>
              <Field label="PAN *" hint="Characters 3–12 of the GSTIN">{(id) => <Input id={id} value={effectivePan} maxLength={10} className="font-mono" onChange={(e) => setPan(e.target.value.toUpperCase())} />}</Field>
            </div>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5" checked={moveAddress} onChange={(e) => setMoveAddress(e.target.checked)} />
              <span>The registered address changes too (e.g. a move to another state)</span>
            </label>
            {moveAddress && addressFields(g.slice(0, 2) || undefined)}
          </>
        )}
        {group === 'ADDRESS' && addressFields()}
        {group === 'CONTACT' && (
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="New contact e-mail" hint={supplier.contact_email ? `Now ${supplier.contact_email}` : undefined}>{(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <Field label="New phone" hint={current.phone ? `Now ${current.phone}` : undefined}>{(id) => <Input id={id} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 …" />}</Field>
          </div>
        )}
        <Field label="Reason and evidence *">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. GST registration amended on 12 Oct; certificate received by e-mail" />}</Field>
        {problems.length > 0 && <ul role="alert" className="list-disc pl-5 text-sm text-red-800">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        <p className="text-xs text-slate-500">You cannot approve your own request. Finance and the supplier manager approve in parallel; a rejection by either ends the request.</p>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={submit.isPending} onClick={go}>Send for approval</Button>
        </div>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- M04 punch-out configuration
export function PunchoutCard({ supplier, manager }: { supplier: SupplierLite; manager: boolean }) {
  const config = supplier.punchout ?? {};
  const [editing, setEditing] = useState(false);
  if (!manager && !config.url) return null;
  return (
    <Card title="Punch-out catalogue (M04)" actions={manager ? <Button onClick={() => setEditing(true)}>{config.url ? 'Change' : 'Configure'}</Button> : undefined}>
      {config.url ? (
        <Facts items={[
          ['Protocol', config.protocol === 'OCI' ? 'SAP OCI' : 'cXML 1.2'],
          ['Endpoint', config.url === 'builtin' ? 'Built-in test catalogue' : <span key="u" className="break-all font-mono text-xs">{config.url}</span>],
          ['Identity', <span key="i" className="font-mono">{config.identity}</span>],
          ['Configured', `${dateTime(config.configuredAt)}${config.configuredBy ? ` by ${config.configuredBy}` : ''}`],
        ]} />
      ) : <Empty title="No punch-out catalogue" hint="Requesters can shop in the supplier's own web shop once its punch-out endpoint is configured." />}
      <p className="mt-2 text-xs text-slate-500">The shared secret is stored encrypted and is never shown again.</p>
      {editing && <PunchoutDialog supplier={supplier} onClose={() => setEditing(false)} />}
    </Card>
  );
}

function PunchoutDialog({ supplier, onClose }: { supplier: SupplierLite; onClose: () => void }) {
  const config = supplier.punchout ?? {};
  const [protocol, setProtocol] = useState(config.protocol ?? 'CXML');
  const [builtin, setBuiltin] = useState(config.url === 'builtin');
  const [url, setUrl] = useState(config.url && config.url !== 'builtin' ? config.url : '');
  const [identity, setIdentity] = useState(config.identity ?? '');
  const [secret, setSecret] = useState('');
  const first = !config.url;
  const valid = (builtin || /^https?:\/\/\S+$/.test(url.trim())) && !!identity.trim() && (first ? secret.length >= 8 : secret === '' || secret.length >= 8);
  const save = useCommand(() => api.put(`/suppliers/${encodeURIComponent(supplier.code)}/punchout`, {
    protocol, url: builtin ? 'builtin' : url.trim(), identity: identity.trim(), sharedSecret: secret || undefined,
  }), { success: 'Punch-out configuration saved', onSuccess: onClose });
  return (
    <Dialog open title={`Punch-out – ${supplier.code}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Protocol">{(id) => (
          <Select id={id} value={protocol} onChange={(e) => setProtocol(e.target.value)} options={[{ value: 'CXML', label: 'cXML 1.2 (PunchOutSetupRequest)' }, { value: 'OCI', label: 'SAP OCI 4.0 (HOOK_URL)' }]} />
        )}</Field>
        <Field label="Identity *" hint={protocol === 'OCI' ? 'OCI user name' : 'Supplier network / DUNS id (To credential)'}>{(id) => <Input id={id} value={identity} onChange={(e) => setIdentity(e.target.value)} />}</Field>
        <div className="md:col-span-2">
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5" checked={builtin} onChange={(e) => setBuiltin(e.target.checked)} />
            <span>Use the built-in test catalogue (this supplier&apos;s catalogue items) instead of a real endpoint</span>
          </label>
        </div>
        {!builtin && (
          <div className="md:col-span-2"><Field label="Supplier punch-out URL *">{(id) => <Input id={id} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://shop.supplier.example/punchout" />}</Field></div>
        )}
        <div className="md:col-span-2">
          <Field label={`Shared secret${first ? ' *' : ''}`} hint={first ? 'At least 8 characters' : 'Leave empty to keep the stored secret'}>{(id) => (
            <Input id={id} type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" />
          )}</Field>
        </div>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Dialog>
  );
}
