'use client';

// ADM-01 organisation and tenant setup: company codes, plants (state, working days, holidays), storage locations, cost objects,
// purchasing organisations and groups, currencies, FX rates. Administrators create, edit, deactivate and delete (a record that
// anything refers to is deactivated instead); everyone else reads. Each record's version travels as If-Match.

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Facts, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Rec = { id: string; version: number; active: boolean; code: string } & Record<string, unknown>;
type Org = {
  tenant: { code: string; name: string; industryTemplate: string; templateName: string | null; baseCurrency: string; timezone: string };
  companyCodes: Rec[]; plants: (Rec & { storageLocations: Rec[] })[]; costObjects: Rec[]; purchasingOrgs: Rec[]; purchasingGroups: Rec[];
  currencies: Rec[]; fxRates: { from: string; to: string; rate: string; validFrom: string; source: string }[];
};
type UserRow = { id: string; name: string; email: string; supplierUser: boolean; active: boolean };

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const COST_TYPES = ['COST_CENTER', 'WBS', 'ORDER', 'ASSET'];

function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
}

type FieldSpec = { key: string; label: string; kind?: 'text' | 'number' | 'select' | 'days' | 'buyers'; options?: { value: string; label: string }[];
  createOnly?: boolean; required?: boolean; hint?: string; upper?: boolean };
type KindSpec = { path: string; title: string; fields: (org: Org) => FieldSpec[]; initial: (r: Rec | null, org: Org) => Record<string, unknown> };

const opts = (codes: string[]) => codes.map((c) => ({ value: c, label: c }));
const activeCodes = (rows: Rec[]) => rows.filter((r) => r.active).map((r) => r.code);

const KINDS: Record<string, KindSpec> = {
  'company-codes': {
    path: 'company-codes', title: 'Company code',
    fields: (o) => [
      { key: 'code', label: 'Company code', createOnly: true, required: true, upper: true, hint: '1-10 characters; cannot change later' },
      { key: 'name', label: 'Legal entity', required: true },
      { key: 'gstin', label: 'GSTIN', upper: true, hint: '15 characters with check digit; leave empty if not registered' },
      { key: 'currency', label: 'Currency', kind: 'select', options: opts(activeCodes(o.currencies)) },
      { key: 'fiscal_year_start_month', label: 'Fiscal year starts', kind: 'select', options: MONTHS.map((m, i) => ({ value: String(i + 1), label: m })) },
    ],
    initial: (r, o) => ({ code: '', name: r?.name ?? '', gstin: r?.gstin ?? '', currency: r?.currency ?? o.tenant.baseCurrency,
      fiscal_year_start_month: String(r?.fiscalYearStartMonth ?? 4) }),
  },
  plants: {
    path: 'plants', title: 'Plant',
    fields: (o) => [
      { key: 'code', label: 'Plant code', createOnly: true, required: true, upper: true },
      { key: 'company_code', label: 'Company code', kind: 'select', createOnly: true, options: opts(activeCodes(o.companyCodes)) },
      { key: 'name', label: 'Plant name', required: true },
      { key: 'state_code', label: 'GST state code', required: true, hint: '2 digits, e.g. 33 Tamil Nadu, 27 Maharashtra' },
      { key: 'working_days', label: 'Working days', kind: 'days' },
    ],
    initial: (r, o) => ({ code: '', company_code: r?.companyCode ?? activeCodes(o.companyCodes)[0] ?? '', name: r?.name ?? '', state_code: r?.stateCode ?? '',
      working_days: r?.workingDays ?? [0, 1, 2, 3, 4, 5] }),
  },
  'storage-locations': {
    path: 'storage-locations', title: 'Storage location',
    fields: (o) => [
      { key: 'plant', label: 'Plant', kind: 'select', createOnly: true, options: opts(activeCodes(o.plants)) },
      { key: 'code', label: 'Location code', createOnly: true, required: true, upper: true },
      { key: 'name', label: 'Name', required: true },
    ],
    initial: (r, o) => ({ plant: r?.plant ?? activeCodes(o.plants)[0] ?? '', code: '', name: r?.name ?? '' }),
  },
  'cost-objects': {
    path: 'cost-objects', title: 'Cost object',
    fields: (o) => [
      { key: 'type', label: 'Type', kind: 'select', createOnly: true, options: COST_TYPES.map((t) => ({ value: t, label: label(t) })) },
      { key: 'code', label: 'Code', createOnly: true, required: true, upper: true, hint: 'Cost centre, WBS element, internal order or asset number' },
      { key: 'company_code', label: 'Company code', kind: 'select', createOnly: true, options: opts(activeCodes(o.companyCodes)) },
      { key: 'name', label: 'Name', required: true },
    ],
    initial: (r, o) => ({ type: r?.type ?? 'COST_CENTER', code: '', company_code: r?.companyCode ?? activeCodes(o.companyCodes)[0] ?? '', name: r?.name ?? '' }),
  },
  'purchasing-orgs': {
    path: 'purchasing-orgs', title: 'Purchasing organisation',
    fields: (o) => [
      { key: 'code', label: 'Code', createOnly: true, required: true, upper: true },
      { key: 'company_code', label: 'Company code', kind: 'select', createOnly: true, options: opts(activeCodes(o.companyCodes)) },
      { key: 'name', label: 'Name', required: true },
    ],
    initial: (r, o) => ({ code: '', company_code: r?.companyCode ?? activeCodes(o.companyCodes)[0] ?? '', name: r?.name ?? '' }),
  },
  'purchasing-groups': {
    path: 'purchasing-groups', title: 'Purchasing group',
    fields: (o) => [
      { key: 'code', label: 'Code', createOnly: true, required: true, upper: true },
      { key: 'name', label: 'Name', required: true },
      { key: 'purchasing_org', label: 'Purchasing organisation', kind: 'select', options: [{ value: '', label: '(none)' }, ...opts(activeCodes(o.purchasingOrgs))] },
      { key: 'plant', label: 'Plant', kind: 'select', options: [{ value: '', label: '(all plants)' }, ...opts(activeCodes(o.plants))] },
      { key: 'buyer_user_ids', label: 'Buyers', kind: 'buyers' },
    ],
    initial: (r) => ({ code: '', name: r?.name ?? '', purchasing_org: r?.purchasingOrg ?? '', plant: r?.plant ?? '', buyer_user_ids: r?.buyerUserIds ?? [] }),
  },
  currencies: {
    path: 'currencies', title: 'Currency',
    fields: () => [
      { key: 'code', label: 'ISO code', createOnly: true, required: true, upper: true, hint: '3 letters, e.g. USD' },
      { key: 'name', label: 'Name', required: true },
      { key: 'decimals', label: 'Decimals', kind: 'number', hint: '0-4; fixed once the currency is in use' },
    ],
    initial: (r) => ({ code: '', name: r?.name ?? '', decimals: String(r?.decimals ?? 2) }),
  },
};

function MasterDialog({ kind, record, org, onClose }: { kind: string; record: Rec | null; org: Org; onClose: () => void }) {
  const spec = KINDS[kind];
  const [f, setF] = useState<Record<string, unknown>>(() => spec.initial(record, org));
  const [reason, setReason] = useState('');
  const [invalid, setInvalid] = useState<string | null>(null);
  const users = useApi<UserRow[]>(spec.fields(org).some((x) => x.kind === 'buyers') ? '/admin/users' : null);
  const fields = spec.fields(org).filter((x) => !(record && x.createOnly));
  const cmd = useCommand((body: Record<string, unknown>) => record
    ? api.put(`/admin/org/${spec.path}/${record.id}`, body, { ifMatch: `"${record.version}"` })
    : api.post(`/admin/org/${spec.path}`, body), {
    success: record ? `${spec.title} updated` : `${spec.title} created`, onSuccess: onClose,
  });
  const set = (k: string, v: unknown) => setF((x) => ({ ...x, [k]: v }));

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    for (const x of fields) {
      let v = f[x.key];
      if (typeof v === 'string') {
        v = v.trim();
        if (x.upper) v = (v as string).toUpperCase();
      }
      if (x.required && !v) { setInvalid(`${x.label} is required.`); return; }
      if (x.kind === 'number' || x.key === 'fiscal_year_start_month') v = Number(v);
      if (x.kind === 'select' && v === '' && x.key !== 'purchasing_org' && x.key !== 'plant') { setInvalid(`${x.label} is required.`); return; }
      if (v === '' && ['gstin', 'purchasing_org', 'plant'].includes(x.key)) v = null;
      body[x.key] = v;
    }
    setInvalid(null);
    if (record && reason.trim()) body.reason = reason.trim();
    cmd.mutate(body);
  }

  return (
    <Dialog open title={record ? `Edit ${spec.title.toLowerCase()} ${record.code}` : `New ${spec.title.toLowerCase()}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map((x) => (
            <Field key={x.key} label={x.label} hint={x.hint} required={x.required}>
              {(id) => x.kind === 'select' ? (
                <Select id={id} value={String(f[x.key] ?? '')} onChange={(e) => set(x.key, e.target.value)} options={x.options ?? []} />
              ) : x.kind === 'days' ? (
                <div id={id} className="flex flex-wrap gap-2">
                  {WEEKDAYS.map((d, i) => {
                    const days = (f[x.key] as number[]) ?? [];
                    return (
                      <label key={d} className="flex items-center gap-1 text-sm">
                        <input type="checkbox" className="h-4 w-4" checked={days.includes(i)}
                          onChange={() => set(x.key, days.includes(i) ? days.filter((v) => v !== i) : [...days, i].sort())} />{d}
                      </label>
                    );
                  })}
                </div>
              ) : x.kind === 'buyers' ? (
                <div id={id} className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2">
                  {(users.data ?? []).filter((u) => !u.supplierUser && u.active).map((u) => {
                    const ids = (f[x.key] as string[]) ?? [];
                    return (
                      <label key={u.id} className="flex items-center gap-2 text-sm">
                        <input type="checkbox" className="h-4 w-4" checked={ids.includes(u.id)}
                          onChange={() => set(x.key, ids.includes(u.id) ? ids.filter((v) => v !== u.id) : [...ids, u.id])} />{u.name} <span className="text-xs text-slate-500">{u.email}</span>
                      </label>
                    );
                  })}
                  {users.isLoading && <Loading />}
                </div>
              ) : (
                <Input id={id} type={x.kind === 'number' ? 'number' : 'text'} value={String(f[x.key] ?? '')} onChange={(e) => set(x.key, e.target.value)} />
              )}
            </Field>
          ))}
        </div>
        {record && <Field label="Reason (optional)">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Renamed after re-registration" />}</Field>}
        {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={cmd.isPending}>{record ? 'Save' : 'Create'}</Button>
        </div>
      </form>
    </Dialog>
  );
}

function RemoveDialog({ kind, record, onClose }: { kind: string; record: Rec; onClose: () => void }) {
  const spec = KINDS[kind];
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.delete<{ outcome: string; reason?: string }>(`/admin/org/${spec.path}/${record.id}?reason=${encodeURIComponent(reason.trim())}`), {
    success: (r) => (r.outcome === 'DELETED' ? `${spec.title} ${record.code} deleted` : `${spec.title} ${record.code} deactivated: other records refer to it`), onSuccess: onClose,
  });
  return (
    <Dialog open title={`Remove ${spec.title.toLowerCase()} ${record.code}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">A record nothing refers to is deleted. If documents or other master data refer to it, it is deactivated instead:
          it leaves the selection lists and stays on history.</p>
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="danger" disabled={reason.trim().length < 3} busy={cmd.isPending} onClick={() => cmd.mutate()}>Remove</Button>
        </div>
      </div>
    </Dialog>
  );
}

function HolidayDialog({ plant, onClose }: { plant: Rec; onClose: () => void }) {
  const [dates, setDates] = useState('');
  const [source, setSource] = useState('');
  const [invalid, setInvalid] = useState<string | null>(null);
  const holidays = (plant.holidays as string[]) ?? [];
  const add = useCommand((body: { dates: string[]; source: string }) => api.post(`/admin/org/plants/${plant.id}/holidays`, body), {
    success: (r) => `${(r as { added: string[] }).added.length} holiday(s) added to ${plant.code}`, onSuccess: onClose,
  });
  const remove = useCommand((day: string) => api.delete(`/admin/org/plants/${plant.id}/holidays/${day}?reason=${encodeURIComponent(source.trim() || 'Entered in error')}`), {
    success: 'Holiday removed',
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    const list = dates.split(/[\s,;]+/).filter(Boolean);
    if (!list.length || list.some((d) => !/^\d{4}-\d{2}-\d{2}$/.test(d))) { setInvalid('Enter dates as YYYY-MM-DD, separated by commas or spaces.'); return; }
    if (source.trim().length < 5) { setInvalid('Name the gazette notification or order the dates come from.'); return; }
    setInvalid(null);
    add.mutate({ dates: list, source: source.trim() });
  }
  return (
    <Dialog open title={`Calendar · plant ${plant.code}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <p className="text-xs text-slate-600">Holidays are added, never silently replaced: planned dates already computed keep their basis. Removing one needs a reason.</p>
        <div className="flex flex-wrap gap-1.5">
          {holidays.length === 0 && <span className="text-sm text-slate-500">No holidays yet</span>}
          {holidays.map((h) => (
            <span key={h} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs">{date(h)}
              <button type="button" aria-label={`Remove ${h}`} className="text-slate-500 hover:text-red-700" disabled={remove.isPending || source.trim().length < 5}
                title={source.trim().length < 5 ? 'Fill in the source/reason below first' : 'Remove'} onClick={() => remove.mutate(h)}>×</button>
            </span>
          ))}
        </div>
        <Field label="New holiday dates" hint="YYYY-MM-DD, separated by commas">{(id) => <Input id={id} value={dates} onChange={(e) => setDates(e.target.value)} placeholder="2027-01-26, 2027-08-15" />}</Field>
        <Field label="Source (also the reason when removing)" hint="e.g. Tamil Nadu Government Gazette 2027 holiday list">{(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} />}</Field>
        {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
        <ProblemBox error={add.error ?? remove.error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Close</Button>
          <Button type="submit" variant="primary" busy={add.isPending}>Add holidays</Button>
        </div>
      </form>
    </Dialog>
  );
}

type Dlg = { kind: string; record: Rec | null } | { remove: { kind: string; record: Rec } } | { holidays: Rec } | null;

function MasterCard({ kind, title, rows, isAdmin, columns, setDialog }: {
  kind: string; title: string; rows: Rec[]; isAdmin: boolean; setDialog: (d: Dlg) => void;
  columns: { key: string; header: string; render: (r: Rec) => React.ReactNode }[];
}) {
  const toggle = useCommand((r: Rec) => api.post(`/admin/org/${KINDS[kind].path}/${r.id}/${r.active ? 'deactivate' : 'activate'}`, { reason: 'Changed in administration' }), {
    success: (r) => `${KINDS[kind].title} ${(r as Rec).code} ${(r as Rec).active ? 'activated' : 'deactivated'}`,
  });
  return (
    <Card title={`${title} (${rows.length})`} actions={isAdmin ? <Button variant="primary" onClick={() => setDialog({ kind, record: null })}>Add</Button> : undefined}>
      <DataTable<Rec> rows={rows} empty={`No ${title.toLowerCase()}`} columns={[
        ...columns,
        { key: 'active', header: 'Status', render: (r) => <StatusChip status={r.active ? 'ACTIVE' : 'INACTIVE'} /> },
        ...(isAdmin ? [{ key: 'actions', header: '', render: (r: Rec) => (
          <div className="flex justify-end gap-1">
            {kind === 'plants' && <Button variant="ghost" onClick={() => setDialog({ holidays: r })}>Calendar</Button>}
            <Button variant="ghost" onClick={() => setDialog({ kind, record: r })}>Edit</Button>
            <Button variant="ghost" busy={toggle.isPending && toggle.variables?.id === r.id} onClick={() => toggle.mutate(r)}>{r.active ? 'Deactivate' : 'Activate'}</Button>
            <Button variant="ghost" onClick={() => setDialog({ remove: { kind, record: r } })}>Remove</Button>
          </div>
        ) }] : []),
      ]} />
      <ProblemBox error={toggle.error} />
    </Card>
  );
}

const mono = (v: unknown) => <span className="font-mono text-xs font-semibold">{String(v ?? '–')}</span>;

export function OrganisationTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<Org>('/admin/organisation');
  const [dialog, setDialog] = useState<Dlg>(null);
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  const sloc = data.plants.flatMap((p) => p.storageLocations);
  return (
    <div className="space-y-4">
      <Card title="Organisation (ADM-01)">
        <Facts items={[
          ['Tenant', `${data.tenant.name} (${data.tenant.code})`], ['Industry template', data.tenant.templateName ?? label(data.tenant.industryTemplate)],
          ['Base currency', data.tenant.baseCurrency], ['Time zone', data.tenant.timezone],
        ]} />
        {!isAdmin && <p className="mt-3 text-xs text-slate-500">You can read the organisation. Changes need the tenant administrator role.</p>}
      </Card>
      <MasterCard kind="company-codes" title="Company codes" rows={data.companyCodes} isAdmin={isAdmin} setDialog={setDialog} columns={[
        { key: 'code', header: 'Code', render: (c) => mono(c.code) }, { key: 'name', header: 'Legal entity', render: (c) => String(c.name) },
        { key: 'gstin', header: 'GSTIN', render: (c) => mono(c.gstin) }, { key: 'currency', header: 'Currency', render: (c) => String(c.currency) },
        { key: 'fy', header: 'Fiscal year starts', render: (c) => MONTHS[Number(c.fiscalYearStartMonth) - 1] ?? String(c.fiscalYearStartMonth) },
      ]} />
      <MasterCard kind="plants" title="Plants and calendars" rows={data.plants} isAdmin={isAdmin} setDialog={setDialog} columns={[
        { key: 'code', header: 'Plant', render: (p) => <span>{mono(p.code)} {String(p.name)}</span> }, { key: 'company', header: 'Company', render: (p) => String(p.companyCode) },
        { key: 'state', header: 'GST state', render: (p) => String(p.stateCode ?? '–') },
        { key: 'days', header: 'Working days', render: (p) => <span className="text-xs">{((p.workingDays as number[]) ?? []).map((d) => WEEKDAYS[d] ?? d).join(' ') || '–'}</span> },
        { key: 'holidays', header: 'Holidays', render: (p) => <span className="text-xs">{(p.holidays as string[]).length ? (p.holidays as string[]).map((h) => date(h)).join(' · ') : '–'}</span> },
      ]} />
      <MasterCard kind="storage-locations" title="Storage locations" rows={sloc} isAdmin={isAdmin} setDialog={setDialog} columns={[
        { key: 'plant', header: 'Plant', render: (s) => mono(s.plant) }, { key: 'code', header: 'Location', render: (s) => mono(s.code) }, { key: 'name', header: 'Name', render: (s) => String(s.name) },
      ]} />
      <MasterCard kind="cost-objects" title="Cost objects" rows={data.costObjects} isAdmin={isAdmin} setDialog={setDialog} columns={[
        { key: 'type', header: 'Type', render: (c) => label(String(c.type)) }, { key: 'code', header: 'Code', render: (c) => mono(c.code) },
        { key: 'name', header: 'Name', render: (c) => String(c.name) }, { key: 'company', header: 'Company', render: (c) => String(c.companyCode) },
      ]} />
      <div className="grid gap-4 xl:grid-cols-2">
        <MasterCard kind="purchasing-orgs" title="Purchasing organisations" rows={data.purchasingOrgs} isAdmin={isAdmin} setDialog={setDialog} columns={[
          { key: 'code', header: 'Code', render: (c) => mono(c.code) }, { key: 'name', header: 'Name', render: (c) => String(c.name) }, { key: 'company', header: 'Company', render: (c) => String(c.companyCode) },
        ]} />
        <MasterCard kind="purchasing-groups" title="Purchasing groups" rows={data.purchasingGroups} isAdmin={isAdmin} setDialog={setDialog} columns={[
          { key: 'code', header: 'Code', render: (c) => mono(c.code) }, { key: 'name', header: 'Name', render: (c) => String(c.name) },
          { key: 'org', header: 'Org', render: (c) => String(c.purchasingOrg ?? '–') }, { key: 'plant', header: 'Plant', render: (c) => String(c.plant ?? '–') },
          { key: 'buyers', header: 'Buyers', render: (c) => String((c.buyerUserIds as string[]).length) },
        ]} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <MasterCard kind="currencies" title="Currencies" rows={data.currencies} isAdmin={isAdmin} setDialog={setDialog} columns={[
          { key: 'code', header: 'Code', render: (c) => mono(c.code) }, { key: 'name', header: 'Name', render: (c) => String(c.name) }, { key: 'dec', header: 'Decimals', render: (c) => String(c.decimals) },
        ]} />
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
      {dialog && 'kind' in dialog && <MasterDialog kind={dialog.kind} record={dialog.record} org={data} onClose={() => setDialog(null)} />}
      {dialog && 'remove' in dialog && <RemoveDialog kind={dialog.remove.kind} record={dialog.remove.record} onClose={() => setDialog(null)} />}
      {dialog && 'holidays' in dialog && <HolidayDialog plant={dialog.holidays} onClose={() => setDialog(null)} />}
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
