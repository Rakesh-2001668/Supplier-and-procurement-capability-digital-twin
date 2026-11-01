'use client';

// ADM-03 approval matrix (DMN-01, requisition approval route by value band) as an editable grid. Saving creates a new
// effective-dated rule version (never an edit); documents in flight keep the version they started under. Check the result
// in the approval simulation tab.

import { FormEvent, useState } from 'react';
import { Button, Card, DataTable, Field, Input, Loading, ProblemBox } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Band = { upTo: number | null; chain: string[]; autoChannels?: string[] };
type Dmn01 = { bands: Band[]; assetAdds?: string[]; slaBusinessDays?: number } & Record<string, unknown>;
type RuleRow = { id: string; key: string; version: string; company_code: string | null; plant: string | null; category: string | null; purchase_type: string | null;
  supplier_group: string | null; effective_from: string; effective_to: string | null; body: Dmn01; description: string | null; created_at: string };
type RoleRow = { role: string; kind: string };

const CHANNELS = ['CATALOGUE', 'CONTRACT'];
// Approvers a band can name: the roles that work approval tasks in the blueprint, plus the tenant's own roles.
const APPROVERS = ['COST_OBJECT_OWNER', 'DEPT_HEAD', 'PROCUREMENT_HEAD', 'FINANCE_CONTROLLER', 'CPO', 'CAPEX_COMMITTEE'];

function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date());
}

function Grid({ current, roles, onClose }: { current: RuleRow; roles: string[]; onClose: () => void }) {
  const [bands, setBands] = useState<{ upTo: string; chain: string[]; auto: string[] }[]>(() => current.body.bands.map((b) => ({
    upTo: b.upTo === null ? '' : String(b.upTo / 100), chain: [...b.chain], auto: [...(b.autoChannels ?? [])] })));
  const [assetAdds, setAssetAdds] = useState<string[]>(current.body.assetAdds ?? []);
  const [sla, setSla] = useState(String(current.body.slaBusinessDays ?? 2));
  const [version, setVersion] = useState('');
  const [from, setFrom] = useState(today());
  const [note, setNote] = useState('');
  const [invalid, setInvalid] = useState<string | null>(null);
  const columns = Array.from(new Set([...APPROVERS, ...roles, ...bands.flatMap((b) => b.chain), ...assetAdds]));
  const save = useCommand((body: Record<string, unknown>) => api.post('/admin/rules', body), {
    success: `DMN-01 version ${version} saved, effective ${from}`, onSuccess: onClose,
  });
  const setBand = (i: number, patch: Partial<(typeof bands)[number]>) => setBands((bs) => bs.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!bands.length) { setInvalid('Add at least one band.'); return; }
    let previous = 0;
    const out: Band[] = [];
    for (let i = 0; i < bands.length; i++) {
      const b = bands[i];
      const last = i === bands.length - 1;
      if (last && b.upTo.trim() !== '') { setInvalid('The last band must be open-ended: leave its limit empty.'); return; }
      if (!last) {
        const v = Number(b.upTo);
        if (!b.upTo.trim() || Number.isNaN(v) || v <= previous) { setInvalid(`Band ${i + 1}: the limit must be a number above the previous band (${previous}).`); return; }
        previous = v;
      }
      if (!b.chain.length && !b.auto.length) { setInvalid(`Band ${i + 1}: choose at least one approver.`); return; }
      out.push({ upTo: last ? null : Math.round(Number(b.upTo) * 100), ...(b.auto.length ? { autoChannels: b.auto } : {}), chain: columns.filter((c) => b.chain.includes(c)) });
    }
    if (!version.trim() || !from) { setInvalid('Give the new version a label and an effective-from date.'); return; }
    if (!(Number(sla) >= 1 && Number(sla) <= 60)) { setInvalid('SLA is 1-60 business days.'); return; }
    setInvalid(null);
    save.mutate({ key: 'DMN-01', version: version.trim(), effective_from: from, company_code: current.company_code ?? undefined, plant: current.plant ?? undefined,
      category: current.category ?? undefined, purchase_type: current.purchase_type ?? undefined,
      body: { ...current.body, bands: out, assetAdds, slaBusinessDays: Number(sla) }, description: note.trim() || 'Approval matrix edited in the grid' });
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <caption className="sr-only">Approval route by requisition value band</caption>
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-3 py-2 text-left">Band</th>
              <th scope="col" className="px-3 py-2 text-left">Up to (₹, inclusive)</th>
              <th scope="col" className="px-3 py-2 text-left">Auto-approve via</th>
              {columns.map((c) => <th key={c} scope="col" className="px-2 py-2 text-center">{label(c)}</th>)}
              <th scope="col" className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {bands.map((b, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-3 py-1.5 font-medium">{i + 1}</td>
                <td className="px-3 py-1.5">
                  {i === bands.length - 1 ? <span className="text-slate-500">and above</span> : (
                    <Input aria-label={`Band ${i + 1} limit in rupees`} inputMode="decimal" className="w-32" value={b.upTo} onChange={(e) => setBand(i, { upTo: e.target.value })} />
                  )}
                </td>
                <td className="px-3 py-1.5">
                  {CHANNELS.map((c) => (
                    <label key={c} className="mr-2 text-xs"><input type="checkbox" className="mr-1" checked={b.auto.includes(c)} onChange={() => setBand(i, { auto: toggle(b.auto, c) })} />{label(c)}</label>
                  ))}
                </td>
                {columns.map((c) => (
                  <td key={c} className="px-2 py-1.5 text-center">
                    <input type="checkbox" aria-label={`Band ${i + 1} approver ${label(c)}`} checked={b.chain.includes(c)} onChange={() => setBand(i, { chain: toggle(b.chain, c) })} />
                  </td>
                ))}
                <td className="px-2 py-1.5">{bands.length > 1 && <Button type="button" variant="ghost" onClick={() => setBands((bs) => bs.filter((_, j) => j !== i))}>Remove</Button>}</td>
              </tr>
            ))}
            <tr className="border-t border-slate-100 bg-slate-50/60">
              <td className="px-3 py-1.5 text-xs font-medium" colSpan={3}>Added for capital assets (any band)</td>
              {columns.map((c) => (
                <td key={c} className="px-2 py-1.5 text-center">
                  <input type="checkbox" aria-label={`Asset add-on ${label(c)}`} checked={assetAdds.includes(c)} onChange={() => setAssetAdds((a) => toggle(a, c))} />
                </td>
              ))}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-600">Within a band approvers are asked in the order of the columns, left to right. A value exactly at a limit belongs to the lower band.</p>
      <Button type="button" onClick={() => setBands((bs) => [...bs.slice(0, -1), { upTo: '', chain: [], auto: [] }, bs[bs.length - 1]])}>Add band</Button>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="New version label" required hint={`Current: ${current.version}`}>{(id) => <Input id={id} value={version} onChange={(e) => setVersion(e.target.value)} placeholder="e.g. 2027.1" />}</Field>
        <Field label="Effective from" required>{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        <Field label="SLA (business days)">{(id) => <Input id={id} type="number" min={1} max={60} value={sla} onChange={(e) => setSla(e.target.value)} />}</Field>
        <Field label="Description">{(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
      {invalid && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{invalid}</p>}
      <ProblemBox error={save.error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="primary" busy={save.isPending}>Save as new version</Button>
      </div>
    </form>
  );
}

export function ApprovalMatrixTab({ isAdmin }: { isAdmin: boolean }) {
  const rules = useApi<RuleRow[]>('/admin/rules');
  const roles = useApi<RoleRow[]>(isAdmin ? '/admin/roles' : null);
  const [editing, setEditing] = useState(false);
  if (rules.isLoading) return <Loading />;
  if (rules.error || !rules.data) return <ProblemBox error={rules.error} />;
  const versions = rules.data.filter((r) => r.key === 'DMN-01').sort((a, b) => a.effective_from.localeCompare(b.effective_from) || a.created_at.localeCompare(b.created_at));
  const now = today();
  const inForce = [...versions].reverse().find((r) => !r.company_code && !r.plant && !r.category && !r.purchase_type && r.effective_from <= now && (!r.effective_to || r.effective_to >= now));
  if (!inForce) return <Card title="Approval matrix (DMN-01)"><p className="text-sm text-slate-600">No unscoped DMN-01 rule set is in force today.</p></Card>;
  return (
    <div className="space-y-4">
      <Card title={`Requisition approval matrix · DMN-01@${inForce.version}`}
        actions={isAdmin && !editing ? <Button variant="primary" onClick={() => setEditing(true)}>Edit as a new version</Button> : undefined}>
        <p className="mb-3 text-sm text-slate-600">The approval route of a requisition by value band. In force today: version {inForce.version}, effective {date(inForce.effective_from)}.
          Changes are new effective-dated versions; requisitions already in approval keep the route they started with. Test a change in the approval simulation tab.{!isAdmin && ' Editing needs the tenant administrator role.'}</p>
        {editing ? <Grid current={inForce} roles={(roles.data ?? []).map((r) => r.role)} onClose={() => setEditing(false)} /> : (
          <DataTable<{ id: string; band: number; limit: string; auto: string; chain: string }> rows={inForce.body.bands.map((b, i) => ({
            id: String(i), band: i + 1, limit: b.upTo === null ? 'above the previous limit' : `up to ${inr(b.upTo)}`,
            auto: (b.autoChannels ?? []).map((c) => label(c)).join(', ') || '–', chain: b.chain.map((c) => label(c)).join(' → ') || '–' }))}
            columns={[{ key: 'band', header: 'Band' }, { key: 'limit', header: 'Value' }, { key: 'auto', header: 'Auto-approved via' }, { key: 'chain', header: 'Approval chain' }]} />
        )}
        {!editing && (inForce.body.assetAdds?.length ?? 0) > 0 && <p className="mt-3 text-xs text-slate-600">Capital assets additionally need: {inForce.body.assetAdds!.map((c) => label(c)).join(', ')}.</p>}
      </Card>
      <Card title={`All versions (${versions.length})`}>
        <DataTable<RuleRow> rows={versions} columns={[
          { key: 'version', header: 'Version', render: (r) => <span className="font-mono text-xs">{r.version}</span> },
          { key: 'effective_from', header: 'Effective', render: (r) => <span className="text-xs">{date(r.effective_from)} → {r.effective_to ? date(r.effective_to) : 'open'}</span> },
          { key: 'description', header: 'Description', render: (r) => r.description ?? '–' },
        ]} />
      </Card>
    </div>
  );
}
