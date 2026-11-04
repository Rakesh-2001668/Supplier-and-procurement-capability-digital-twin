'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Input, Loading, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, inr, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { hasRole, today, useSessionUser } from '../../invoices/_components';

type Certificate = { certificateNo: string; section: string | null; ratePct: string; validFrom: string; validTo: string; status: string; validNow: boolean;
  note: string | null; revokedReason: string | null; maxBaseMinor: number | null; consumedBaseMinor: number; remainingBaseMinor: number | null };
type Tcs = { enabled?: boolean; section?: string; ratePct?: number | string; annualThresholdMinor?: number | null; addToPayable?: boolean };
type FinanceView = { supplier: string; name: string; msmeClass: string | null; udyamNo: string | null; tdsSection: string | null; panOnFile: boolean;
  panFromGstin: string | null; gstinOnFile: boolean; isMsme: boolean; msmeWrittenAgreement: boolean | null; etag: string; certificates: Certificate[];
  tdsSections: Record<string, { label: string | null; ratePct: number }> };

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const UDYAM_RE = /^UDYAM-[A-Z]{2}-\d{2}-\d{7}$/;
const MSME_CLASSES = [{ value: '', label: 'Not an MSME' }, { value: 'MICRO', label: 'Micro' }, { value: 'SMALL', label: 'Small' }, { value: 'MEDIUM', label: 'Medium' }];

/** Finance attributes of a supplier (M10): MSME class and Udyam number (45-day payment rule), PAN and TDS section, s.197 certificates. */
export function SupplierFinanceCard({ code }: { code: string }) {
  const user = useSessionUser();
  const canEdit = hasRole(user, 'SUPPLIER_MANAGER', 'FINANCE_CONTROLLER');
  const { data, isLoading, error } = useApi<FinanceView>(`/suppliers/${encodeURIComponent(code)}/finance`);
  const controls = useApi<{ tds: { tcs?: Tcs } }>('/finance/controls');
  const tcs = controls.data?.tds.tcs;
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const revoke = useCommand((c: Certificate) => api.post(`/suppliers/${encodeURIComponent(code)}/tds-certificates/${encodeURIComponent(c.certificateNo)}/revoke`,
    { reason: 'Revoked from the supplier finance screen' }), { success: 'Certificate revoked' });
  return (
    <Card title="Finance · MSME, PAN, TDS" actions={canEdit && data ? <Button onClick={() => setEditing(true)}>Edit</Button> : undefined}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <div className="space-y-4">
          <Facts items={[
            ['MSME class', data.msmeClass ? `${data.msmeClass.toLowerCase()}${data.isMsme ? (data.msmeWrittenAgreement === false ? ' · paid within 15 days of acceptance' : ' · paid within 45 days of acceptance') : ' · outside the 45-day rule'}` : 'not an MSME'],
            ['Udyam number', data.udyamNo ?? '–'],
            ...(data.msmeClass ? [['Written payment agreement', data.msmeWrittenAgreement === false
              ? 'none: MSMED Act s.15 limits the period to 15 days from acceptance' : 'on file: the period agreed in writing, at most 45 days'] as [string, string]] : []),
            ['PAN', data.panOnFile ? (data.panFromGstin ? `on file (${data.panFromGstin} in the GSTIN)` : 'on file') : 'not on file: TDS at the higher no-PAN rate'],
            ['TDS section', data.tdsSection ? `${data.tdsSection}${data.tdsSections[data.tdsSection]?.label ? ` · ${data.tdsSections[data.tdsSection].label}` : ''}` : 'none: nothing is withheld'],
            ['TCS (tenant rule)', !tcs ? '–' : tcs.enabled
              ? `${tcs.section ?? 'TCS'} · ${tcs.ratePct}% of the invoice${tcs.annualThresholdMinor ? ` above ${inr(tcs.annualThresholdMinor)} a year` : ''}${tcs.addToPayable ? ' · paid to the supplier with the invoice' : ' · carried to the ERP only'}`
              : 'off: no TCS is collected on this supplier\'s invoices'],
          ]} />
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">Lower-deduction certificates (s.197)</h3>
              {canEdit && <Button onClick={() => setAdding(true)}>Add certificate</Button>}
            </div>
            {!data.certificates.length ? <Empty title="No certificate" hint="Payments are taxed at the section rate." /> : (
              <DataTable<Certificate> rows={data.certificates.map((c) => ({ ...c, id: c.certificateNo }))} columns={[
                { key: 'certificateNo', header: 'Certificate', render: (c) => <span className="font-mono text-xs">{c.certificateNo}</span> },
                { key: 'section', header: 'Section', render: (c) => c.section ?? 'all' },
                { key: 'ratePct', header: 'Rate %', align: 'right' },
                { key: 'cap', header: 'Amount cap (taxable base)', align: 'right', render: (c) => c.maxBaseMinor === null ? <span className="text-slate-500">no cap</span> : (
                  <><p>{inr(c.maxBaseMinor)}</p>
                    <p className="text-xs text-slate-500">consumed {inr(c.consumedBaseMinor)} · remaining {inr(c.remainingBaseMinor ?? 0)}</p>
                    <div className="mt-1 h-1.5 w-32 rounded bg-slate-100" role="img" aria-label={`${Math.min(100, Math.round((c.consumedBaseMinor / c.maxBaseMinor) * 100))} percent of the cap consumed`}>
                      <div className={`h-1.5 rounded ${c.consumedBaseMinor >= c.maxBaseMinor ? 'bg-red-500' : 'bg-[#1A56DB]'}`} style={{ width: `${Math.min(100, (c.consumedBaseMinor / c.maxBaseMinor) * 100)}%` }} />
                    </div></>
                ) },
                { key: 'validFrom', header: 'Valid', render: (c) => `${date(c.validFrom)} – ${date(c.validTo)}` },
                { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status === 'ACTIVE' && !c.validNow ? 'EXPIRED' : c.status} /> },
                { key: 'action', header: '', render: (c) => canEdit && c.status === 'ACTIVE' ? <Button variant="danger" busy={revoke.isPending} onClick={() => revoke.mutate(c)}>Revoke</Button> : null },
              ]} />
            )}
          </div>
        </div>
      )}
      {editing && data && <EditDialog code={code} view={data} onClose={() => setEditing(false)} />}
      {adding && data && <CertificateDialog code={code} sections={Object.keys(data.tdsSections)} onClose={() => setAdding(false)} />}
    </Card>
  );
}

function EditDialog({ code, view, onClose }: { code: string; view: FinanceView; onClose: () => void }) {
  const [msme, setMsme] = useState(view.msmeClass ?? '');
  const [udyam, setUdyam] = useState(view.udyamNo ?? '');
  const [pan, setPan] = useState('');
  const [section, setSection] = useState(view.tdsSection ?? '');
  const [agreement, setAgreement] = useState(view.msmeWrittenAgreement !== false);
  const [reason, setReason] = useState('');
  const problems = [
    udyam.trim() && !UDYAM_RE.test(udyam.trim().toUpperCase()) ? 'Udyam number looks like UDYAM-KA-03-0012345' : '',
    msme && !udyam.trim() ? 'An MSME class needs the Udyam number' : '',
    pan.trim() && !PAN_RE.test(pan.trim().toUpperCase()) ? 'PAN is 5 letters, 4 digits and a letter' : '',
    reason.trim().length < 3 ? 'Give a reason' : '',
  ].filter(Boolean);
  const save = useCommand(() => api.put(`/suppliers/${encodeURIComponent(code)}/finance`, {
    msmeClass: msme || undefined, udyamNo: udyam.trim() ? udyam.trim().toUpperCase() : undefined, tdsSection: section || undefined,
    pan: pan.trim() ? pan.trim().toUpperCase() : undefined, reason: reason.trim(),
    msmeWrittenAgreement: msme && agreement !== (view.msmeWrittenAgreement !== false) ? agreement : undefined,
  }, { ifMatch: view.etag }), { success: 'Finance attributes saved', onSuccess: onClose });
  return (
    <Dialog open title={`Finance attributes · ${view.supplier}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="MSME class">{(id) => <Select id={id} value={msme} onChange={(e) => setMsme(e.target.value)} options={MSME_CLASSES} />}</Field>
        <Field label="Udyam registration number" hint="UDYAM-KA-03-0012345">{(id) => <Input id={id} maxLength={30} value={udyam} onChange={(e) => setUdyam(e.target.value)} />}</Field>
        <Field label="PAN" hint={view.panOnFile ? 'On file; enter only to replace it. Must match the GSTIN.' : 'Not on file'}>
          {(id) => <Input id={id} maxLength={10} placeholder="AABCT1234K" value={pan} onChange={(e) => setPan(e.target.value)} />}
        </Field>
        <Field label="TDS section">{(id) => <Select id={id} value={section} onChange={(e) => setSection(e.target.value)}
          options={[{ value: '', label: 'None: nothing is withheld' }, ...Object.entries(view.tdsSections).map(([k, v]) => ({ value: k, label: `${k}${v.label ? ` · ${v.label}` : ''} · ${v.ratePct}%` }))]} />}</Field>
        {msme && (
          <div className="md:col-span-2">
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[#1A56DB]" checked={agreement} onChange={(e) => setAgreement(e.target.checked)} />
              <span>A written agreement fixes the payment period (at most 45 days from acceptance)
                <span className="block text-xs text-slate-500">MSMED Act s.15: clear this when there is no written agreement; the supplier is then due 15 days from acceptance.</span></span>
            </label>
          </div>
        )}
        <div className="md:col-span-2"><Field label="Reason (audited)">{(id) => <Input id={id} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>
      </div>
      {problems.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-amber-800">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={problems.length > 0} busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Dialog>
  );
}

function CertificateDialog({ code, sections, onClose }: { code: string; sections: string[]; onClose: () => void }) {
  const [no, setNo] = useState('');
  const [section, setSection] = useState('');
  const [rate, setRate] = useState('');
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState('');
  const [note, setNote] = useState('');
  const [cap, setCap] = useState('');
  const valid = no.trim().length >= 6 && rate.trim() !== '' && Number(rate) >= 0 && Number(rate) <= 100 && !!from && !!to && to >= from
    && (cap.trim() === '' || (Number.isFinite(Number(cap)) && Number(cap) > 0));
  const save = useCommand(() => api.post(`/suppliers/${encodeURIComponent(code)}/tds-certificates`, {
    certificateNo: no.trim(), section: section || undefined, ratePct: rate, validFrom: from, validTo: to, note: note.trim() || undefined,
    maxBaseMinor: cap.trim() ? rupeesToMinor(cap) : undefined,
  }), { success: 'Certificate recorded', onSuccess: onClose });
  return (
    <Dialog open title="Lower-deduction certificate (s.197)" onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Certificate number">{(id) => <Input id={id} maxLength={40} value={no} onChange={(e) => setNo(e.target.value)} />}</Field>
        <Field label="Section">{(id) => <Select id={id} value={section} onChange={(e) => setSection(e.target.value)}
          options={[{ value: '', label: 'All sections of the supplier' }, ...sections.map((s) => ({ value: s, label: s }))]} />}</Field>
        <Field label="Rate %" hint="0 for a nil-deduction certificate">{(id) => <Input id={id} type="number" min={0} max={100} step="0.001" value={rate} onChange={(e) => setRate(e.target.value)} />}</Field>
        <Field label="Amount cap in rupees (optional)" hint="Taxable base the certificate covers; beyond it the section rate applies">
          {(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value)} />}
        </Field>
        <Field label="Valid from">{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
        <Field label="Valid to">{(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
        <div className="md:col-span-2"><Field label="Note">{(id) => <Input id={id} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />}</Field></div>
      </div>
      <p className="mt-2 text-xs text-slate-500">While the certificate is valid on the payment date its rate replaces the section rate for this supplier&apos;s payments, up to its amount cap when it has one.</p>
      <ProblemBox error={save.error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>Record certificate</Button>
      </div>
    </Dialog>
  );
}
