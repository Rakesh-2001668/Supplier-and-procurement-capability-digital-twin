'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { AuditTrail, ProcessPath, TaskPanel } from '@/components/pic/object';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip, Tabs, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, label, qty } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';
import { useCertificateVerifier, useSupplierManager } from '../roles';
import { Address, MasterDataCard, PunchoutCard, PunchoutConfig } from './master-data';

type CategoryStatus = { id: string; category: string; status: string; waiver_reason: string | null; qualified_on: string | null; updated_at: string | null };
type Twin = { id: string; category: string; capability: Record<string, string> | null; evidence_level: string | null; free_capacity_per_month: string | null;
  trust_score: string | null; late_delivery_prob: string | null; model_version: string | null; ppm: string | null; lead_time_days: number | null; as_of: string | null };
type Scorecard = { id: string; period: string; receipts: number; on_time_in_full: number; qty_received: string; qty_rejected: string; invoices: number;
  invoices_first_pass: number; otif_pct: string | null; ppm: string | null; invoice_accuracy_pct: string | null };
type Certificate = { id: string; type: string; number: string; issued_on: string; expires_on: string; mandatory_for: string[] | null; verified: boolean; status: string };
type BankAccount = { id: string; account_masked: string; ifsc: string; holder_name: string; active: boolean; verified_on: string | null; payable_from: string | null };
type Qualification = { id: string; category: string; status: string; questionnaire: Record<string, unknown> | null; questionnaire_score: string | null;
  audit_score: string | null; sample_approval: string | null; decision: string | null; decision_reason: string | null; created_at: string };
type Supplier360 = {
  id: string; code: string; legal_name: string; status: string; gstin_masked: string; state_code: string; country: string; segment: string | null;
  risk_tier: string | null; payment_terms: string; incoterms: string | null; twin_ref: string | null; contact_email: string;
  address: Address | null; punchout: PunchoutConfig | null;
  screening: { outcome?: string; duplicates?: { code: string; reason: string }[]; sanctionsHits?: unknown[]; screenedAt?: string; providerError?: string | null;
    disposition?: { decision: string; byName?: string; at?: string; note?: string; screenedAt?: string; mergedInto?: string } } | null;
  categories: CategoryStatus[]; twin: Twin[]; scorecards: Scorecard[]; certificates: Certificate[]; bankAccounts: BankAccount[]; qualifications: Qualification[];
};
type BankChange = { id: string; number: string; supplier_code: string; status: string; bank_account_id: string; created_at: string };
type DecisionResult = { status: string; gaps: string[] };

const pct = (v: string | null | undefined) => (v === null || v === undefined ? '–' : `${(Number(v) * 100).toFixed(0)}%`);

export default function Supplier360Page() {
  const { code } = useParams<{ code: string }>();
  const path = `/suppliers/${encodeURIComponent(code)}`;
  const { data: s, isLoading, error } = useApi<Supplier360>(path);
  const manager = useSupplierManager();
  const verifier = useCertificateVerifier();
  const [dialog, setDialog] = useState<{ kind: 'qualify' | 'block' | 'assess' | 'decide' | 'callback' | 'unblock' | 'bank' | 'screening' | 'verify'; id?: string } | null>(null);
  const changes = useList<BankChange>('/bank-changes?status=PENDING_CALLBACK');
  const pending = changes.items.filter((c) => c.supplier_code === code);

  if (isLoading) return <Loading />;
  if (error || !s) return <ProblemBox error={error} />;
  const openQuals = s.qualifications.filter((q) => q.status === 'OPEN');
  const disposition = s.screening?.disposition;
  const reviewOpen = s.screening?.outcome === 'REVIEW' && !(disposition?.decision === 'CLEARED' && disposition.screenedAt === s.screening.screenedAt);
  const closed = ['BLOCKED', 'MERGED'].includes(s.status);
  const latest = s.scorecards[s.scorecards.length - 1];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-wider text-slate-500">SLM-01 · Supplier 360</p>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-[#0B1020]">{s.legal_name} <span className="text-base font-normal text-slate-500">{s.code}</span></h1>
            <StatusChip status={s.status} />
          </div>
        </div>
        {manager && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setDialog({ kind: 'qualify' })} disabled={closed}>Start qualification</Button>
            {!closed && <Button onClick={() => setDialog({ kind: 'bank' })}>Request bank change</Button>}
            {s.screening?.outcome && s.status !== 'MERGED' && <Button onClick={() => setDialog({ kind: 'screening' })}>{reviewOpen ? 'Dispose screening' : 'Re-screen'}</Button>}
            {!closed && <Button variant="danger" onClick={() => setDialog({ kind: 'block' })}>Block supplier</Button>}
            {s.status === 'BLOCKED' && <Button variant="primary" onClick={() => setDialog({ kind: 'unblock' })}>Unblock supplier</Button>}
          </div>
        )}
      </div>

      <TaskPanel objectRef={s.code} />

      {manager && pending.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50/60 p-4">
          <p className="text-sm font-semibold text-amber-900">Bank detail change awaiting call-back verification</p>
          <p className="text-xs text-amber-900">Call the supplier on an independently known number (not one given in the request) before verifying. The requester cannot verify their own change (MDM-04).</p>
          <ul className="mt-2 space-y-2">
            {pending.map((c) => {
              const acct = s.bankAccounts.find((b) => b.id === c.bank_account_id);
              return (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span><span className="font-mono">{c.number}</span> · {acct ? `${acct.account_masked} · ${acct.ifsc} · ${acct.holder_name}` : 'new account'} · requested {dateTime(c.created_at)}</span>
                  <Button variant="primary" onClick={() => setDialog({ kind: 'callback', id: c.number })}>Verify call-back</Button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {changes.error && <ProblemBox error={changes.error} />}

      {reviewOpen && (
        <div role="status" className="rounded-lg border border-amber-300 bg-amber-50/60 p-4 text-sm text-amber-900">
          <p className="font-semibold">Screening needs review before any category can be qualified or the ERP vendor created (F8-03)</p>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {(s.screening?.duplicates ?? []).map((d) => <li key={d.code}>{d.code}: {d.reason}</li>)}
            {s.screening?.providerError && <li>Sanctions provider error: {s.screening.providerError}</li>}
          </ul>
          <p className="mt-1 text-xs">A supplier manager other than the person who registered the supplier clears it, merges it into the duplicate, or re-screens.</p>
        </div>
      )}

      <Card>
        <Facts items={[
          ['GSTIN', <span key="g" className="font-mono">{s.gstin_masked}</span>],
          ['State / country', `${s.state_code} · ${s.country}`],
          ['Contact', s.contact_email],
          ['Payment terms', s.payment_terms],
          ['Incoterms', s.incoterms ?? '–'],
          ['Segment', s.segment ? label(s.segment) : '–'],
          ['Risk tier', s.risk_tier ?? '–'],
          ['Screening', s.screening?.outcome ? <span key="sc">{label(s.screening.outcome)} <span className="text-xs font-normal text-slate-500">
            {s.screening.duplicates?.length ?? 0} duplicates · {s.screening.sanctionsHits?.length ?? 0} sanctions hits · {dateTime(s.screening.screenedAt)}
            {disposition ? ` · ${label(disposition.decision)} by ${disposition.byName ?? 'supplier manager'}${disposition.mergedInto ? ` into ${disposition.mergedInto}` : ''}` : ''}</span></span> : 'not screened yet'],
        ]} />
      </Card>

      <Card title="Status by category">
        {!s.categories.length ? <Empty title="No categories" /> : (
          <ul className="flex flex-wrap gap-3">
            {s.categories.map((c) => (
              <li key={c.id} className="rounded-lg border border-slate-200 px-3 py-2">
                <div className="flex items-center gap-2"><span className="font-mono text-xs font-semibold">{c.category}</span><StatusChip status={c.status} /></div>
                <p className="mt-0.5 text-xs text-slate-500">{c.qualified_on ? `qualified ${date(c.qualified_on)}` : 'not qualified'}{c.waiver_reason ? ` · waiver: ${c.waiver_reason}` : ''}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <MasterDataCard supplier={s} manager={manager} />

      <PunchoutCard supplier={s} manager={manager} />

      <Card title="Digital twin snapshot">
        {!s.twin.length ? <Empty title="No twin evidence yet" hint="Capacity, trust and delivery-risk evidence appears after qualification and first deliveries." /> : (
          <div className="space-y-4">
            {s.twin.map((t) => (
              <div key={t.id}>
                <p className="mb-2 text-xs text-slate-500"><span className="font-mono font-semibold text-slate-700">{t.category}</span> · as of {date(t.as_of)} · model {t.model_version ?? '–'}
                  {t.capability ? ` · ${Object.entries(t.capability).map(([k, v]) => `${k}: ${v}`).join(', ')}` : ''}</p>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                  <Kpi label="Free capacity / month" value={qty(t.free_capacity_per_month)} />
                  <Kpi label="Trust score" value={pct(t.trust_score)} tone={Number(t.trust_score) >= 0.8 ? 'good' : 'warn'} />
                  <Kpi label="Late-delivery prob." value={pct(t.late_delivery_prob)} tone={Number(t.late_delivery_prob) > 0.2 ? 'warn' : 'good'} />
                  <Kpi label="PPM" value={t.ppm ? qty(t.ppm) : '–'} />
                  <Kpi label="Lead time" value={t.lead_time_days !== null ? `${t.lead_time_days} d` : '–'} />
                  <Kpi label="Evidence level" value={t.evidence_level ?? '–'} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <Tabs tabs={[
          {
            id: 'scorecards', label: `Scorecards${latest ? ` · ${latest.period}` : ''}`, content: (
              <DataTable<Scorecard> rows={[...s.scorecards].reverse()} empty="No performance periods yet" columns={[
                { key: 'period', header: 'Period' },
                { key: 'otif_pct', header: 'OTIF', align: 'right', render: (r) => (r.otif_pct !== null ? `${r.otif_pct}%` : '–') },
                { key: 'receipts', header: 'Receipts (OTIF)', align: 'right', render: (r) => `${r.receipts} (${r.on_time_in_full})` },
                { key: 'ppm', header: 'PPM', align: 'right', render: (r) => qty(r.ppm) },
                { key: 'qty_rejected', header: 'Rejected / received', align: 'right', render: (r) => `${qty(r.qty_rejected)} / ${qty(r.qty_received)}` },
                { key: 'invoice_accuracy_pct', header: 'Invoice accuracy', align: 'right', render: (r) => (r.invoice_accuracy_pct !== null ? `${r.invoice_accuracy_pct}%` : '–') },
                { key: 'invoices', header: 'Invoices (first pass)', align: 'right', render: (r) => `${r.invoices} (${r.invoices_first_pass})` },
              ]} />
            ),
          },
          {
            id: 'certs', label: `Certificates (${s.certificates.length})`, content: (
              <DataTable<Certificate> rows={s.certificates} empty="No certificates" columns={[
                { key: 'type', header: 'Type' },
                { key: 'number', header: 'Number', render: (c) => <span className="font-mono text-xs">{c.number}</span> },
                { key: 'issued_on', header: 'Issued', render: (c) => date(c.issued_on) },
                { key: 'expires_on', header: 'Expires', render: (c) => {
                  const days = Math.ceil((new Date(c.expires_on).getTime() - Date.now()) / 864e5);
                  return <span className={days < 0 ? 'font-semibold text-red-700' : days <= 90 ? 'font-semibold text-amber-700' : ''}>{date(c.expires_on)} {days < 0 ? '(expired)' : days <= 90 ? `(in ${days} d)` : ''}</span>;
                } },
                { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
                { key: 'verified', header: 'Verified', render: (c) => (c.verified ? 'Yes' : 'Not yet') },
                { key: 'mandatory_for', header: 'Mandatory for', render: (c) => c.mandatory_for?.join(', ') || '–' },
                { key: 'actions', header: '', render: (c) => (verifier && !c.verified && c.status === 'VALID' && new Date(c.expires_on).getTime() >= Date.now() - 864e5
                  ? <Button onClick={() => setDialog({ kind: 'verify', id: c.id })}>Verify</Button> : null) },
              ]} />
            ),
          },
          {
            id: 'bank', label: `Bank accounts (${s.bankAccounts.length})`, content: (
              <div>
                <DataTable<BankAccount> rows={s.bankAccounts} empty="No bank account on file" columns={[
                  { key: 'account_masked', header: 'Account', render: (b) => <span className="font-mono">{b.account_masked}</span> },
                  { key: 'ifsc', header: 'IFSC', render: (b) => <span className="font-mono">{b.ifsc}</span> },
                  { key: 'holder_name', header: 'Holder' },
                  { key: 'active', header: 'Status', render: (b) => <StatusChip status={b.active ? 'ACTIVE' : 'PENDING'} /> },
                  { key: 'verified_on', header: 'Verified', render: (b) => date(b.verified_on) },
                  { key: 'payable_from', header: 'Payable from', render: (b) => {
                    if (!b.payable_from) return '–';
                    const cooling = new Date(b.payable_from) > new Date();
                    return <span className={cooling ? 'font-semibold text-amber-700' : ''}>{dateTime(b.payable_from)}{cooling ? ' (cooling-off)' : ''}</span>;
                  } },
                ]} />
                <p className="mt-2 text-xs text-slate-500">Account numbers are masked. A new or changed account needs call-back verification and dual finance approval, then a cooling-off period before payments can go to it.</p>
              </div>
            ),
          },
          {
            id: 'quals', label: `Qualifications (${s.qualifications.length}${openQuals.length ? `, ${openQuals.length} open` : ''})`, content: (
              <DataTable<Qualification> rows={s.qualifications} empty="No qualifications started" columns={[
                { key: 'category', header: 'Category', render: (q) => <span className="font-mono text-xs">{q.category}</span> },
                { key: 'status', header: 'Status', render: (q) => <StatusChip status={q.status === 'DECIDED' ? (q.decision ?? q.status) : q.status} /> },
                { key: 'questionnaire_score', header: 'Questionnaire', align: 'right', render: (q) => q.questionnaire_score ?? '–' },
                { key: 'audit_score', header: 'Audit', align: 'right', render: (q) => q.audit_score ?? '–' },
                { key: 'sample_approval', header: 'Sample', render: (q) => (q.sample_approval ? label(q.sample_approval) : '–') },
                { key: 'decision_reason', header: 'Decision reason', render: (q) => q.decision_reason ?? '–' },
                { key: 'actions', header: '', render: (q) => (manager && q.status === 'OPEN' ? (
                  <div className="flex gap-1.5">
                    <Button onClick={() => setDialog({ kind: 'assess', id: q.id })}>Record assessment</Button>
                    <Button variant="primary" onClick={() => setDialog({ kind: 'decide', id: q.id })}>Decide</Button>
                  </div>
                ) : null) },
              ]} />
            ),
          },
          { id: 'process', label: 'Onboarding process', content: <SupplierProcess supplierCode={s.code} /> },
          { id: 'audit', label: 'Audit', content: <SupplierAudit supplierCode={s.code} /> },
        ]} />
      </Card>

      {dialog?.kind === 'qualify' && <QualifyDialog supplier={s} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'block' && <BlockDialog supplier={s} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'callback' && dialog.id && <CallbackDialog number={dialog.id} supplier={s} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'assess' && <AssessDialog q={s.qualifications.find((q) => q.id === dialog.id)} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'decide' && <DecideDialog q={s.qualifications.find((q) => q.id === dialog.id)} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'unblock' && <UnblockDialog supplier={s} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'bank' && <BankChangeDialog supplier={s} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'screening' && <ScreeningDialog supplier={s} review={reviewOpen} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'verify' && <VerifyCertificateDialog cert={s.certificates.find((c) => c.id === dialog.id)} onClose={() => setDialog(null)} />}
    </div>
  );
}

// ProcessPath and AuditTrail take the document reference in a prop named "ref"; keeping it in a leaf component stops the
// React compiler lint from treating the whole supplier object as a ref.
function SupplierProcess({ supplierCode }: { supplierCode: string }) {
  return <ProcessPath type="SUPPLIER" ref={supplierCode} />;
}

function SupplierAudit({ supplierCode }: { supplierCode: string }) {
  return <AuditTrail type="SUPPLIER" ref={supplierCode} />;
}

function Actions({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return <div className="mt-4 flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button>{children}</div>;
}

function QualifyDialog({ supplier, onClose }: { supplier: Supplier360; onClose: () => void }) {
  const candidates = supplier.categories.filter((c) => !['QUALIFIED', 'PREFERRED', 'UNDER_QUALIFICATION', 'BLOCKED'].includes(c.status)).map((c) => c.category);
  const [category, setCategory] = useState(candidates[0] ?? '');
  const start = useCommand(() => api.post(`/suppliers/${encodeURIComponent(supplier.code)}/qualifications`, { category: category.trim().toUpperCase() }),
    { success: `Qualification started for ${category.trim().toUpperCase()}`, onSuccess: onClose });
  return (
    <Dialog open title={`Start qualification – ${supplier.code}`} onClose={onClose}>
      <Field label="Category" hint="The category status moves to Under qualification until a decision is recorded.">{(id) => (
        <>
          <Input id={id} list="qual-cats" value={category} onChange={(e) => setCategory(e.target.value.toUpperCase())} placeholder="e.g. ALU-DIECAST" />
          <datalist id="qual-cats">{supplier.categories.map((c) => <option key={c.id} value={c.category} />)}</datalist>
        </>
      )}</Field>
      <Actions onClose={onClose}><Button variant="primary" disabled={!category.trim()} busy={start.isPending} onClick={() => start.mutate()}>Start qualification</Button></Actions>
    </Dialog>
  );
}

function AssessDialog({ q, onClose }: { q?: Qualification; onClose: () => void }) {
  const [questionnaire, setQuestionnaire] = useState(q?.questionnaire_score ?? '');
  const [audit, setAudit] = useState(q?.audit_score ?? '');
  const [sample, setSample] = useState(q?.sample_approval ?? '');
  const inRange = (v: string) => v === '' || (Number(v) >= 0 && Number(v) <= 100);
  const valid = inRange(questionnaire) && inRange(audit) && (questionnaire !== '' || audit !== '' || sample !== '');
  const save = useCommand(() => api.post(`/qualifications/${q?.id}/assessment`, {
    questionnaire_score: questionnaire === '' ? undefined : questionnaire, audit_score: audit === '' ? undefined : audit, sample_approval: sample || undefined,
  }), { success: 'Assessment recorded', onSuccess: onClose });
  if (!q) return null;
  return (
    <Dialog open title={`Record assessment – ${q.category}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Questionnaire score (0–100)">{(id) => <Input id={id} type="number" min="0" max="100" value={questionnaire} onChange={(e) => setQuestionnaire(e.target.value)} />}</Field>
        <Field label="Audit score (0–100)">{(id) => <Input id={id} type="number" min="0" max="100" value={audit} onChange={(e) => setAudit(e.target.value)} />}</Field>
        <Field label="Sample approval">{(id) => (
          <Select id={id} value={sample} onChange={(e) => setSample(e.target.value)} options={[
            { value: '', label: 'Not recorded' }, { value: 'PPAP_APPROVED', label: 'PPAP approved' }, { value: 'REJECTED', label: 'Rejected' },
          ]} />
        )}</Field>
      </div>
      {!valid && <p role="alert" className="mt-2 text-sm text-red-700">Enter at least one result; scores must be 0–100.</p>}
      <p className="mt-3 text-xs text-slate-500">Minimum questionnaire and audit scores, mandatory certificates and (for some categories) PPAP sample approval are checked when you decide.</p>
      <Actions onClose={onClose}><Button variant="primary" disabled={!valid} busy={save.isPending} onClick={() => save.mutate()}>Save assessment</Button></Actions>
    </Dialog>
  );
}

function DecideDialog({ q, onClose }: { q?: Qualification; onClose: () => void }) {
  const [decision, setDecision] = useState('QUALIFIED');
  const [reason, setReason] = useState('');
  const [waiver, setWaiver] = useState('');
  const ok = !!reason.trim() && (decision !== 'CONDITIONAL' || !!waiver.trim());
  const decide = useCommand(() => api.post<DecisionResult>(`/qualifications/${q?.id}/decision`, { decision, reason: reason.trim(), waiver: waiver.trim() || undefined }), {
    success: (r) => `Category status: ${label(r.status)}${r.gaps.length ? ` (gaps: ${r.gaps.join('; ')})` : ''}`, onSuccess: onClose });
  if (!q) return null;
  return (
    <Dialog open title={`Qualification decision – ${q.category}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Questionnaire {q.questionnaire_score ?? '–'} · audit {q.audit_score ?? '–'} · sample {q.sample_approval ? label(q.sample_approval) : '–'}</p>
      <div className="grid gap-3">
        <Field label="Decision">{(id) => (
          <Select id={id} value={decision} onChange={(e) => setDecision(e.target.value)} options={[
            { value: 'QUALIFIED', label: 'Qualified – may be invited to sourcing' },
            { value: 'CONDITIONAL', label: 'Conditional – with written waiver' },
            { value: 'REJECTED', label: 'Rejected – exit for this category' },
          ]} />
        )}</Field>
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Audit 88/100; certificates verified" />}</Field>
        {decision === 'CONDITIONAL' && (
          <Field label="Waiver (required for Conditional)" hint="State the gap being waived, the mitigation and the review date.">{(id) => <Textarea id={id} value={waiver} onChange={(e) => setWaiver(e.target.value)} />}</Field>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">Qualified is refused while gaps remain (missing/expired/unverified certificates, low scores, missing PPAP). Qualification also requires a verified, dual-approved bank account. The first qualification creates the supplier master in the ERP.</p>
      <Actions onClose={onClose}><Button variant="primary" disabled={!ok} busy={decide.isPending} onClick={() => decide.mutate()}>Record decision</Button></Actions>
    </Dialog>
  );
}

function CallbackDialog({ number, supplier, onClose }: { number: string; supplier: Supplier360; onClose: () => void }) {
  const [note, setNote] = useState('');
  const verify = useCommand(() => api.post(`/bank-changes/${encodeURIComponent(number)}/callback`, { note: note.trim() }),
    { success: `${number} call-back verified – now awaiting dual finance approval`, onSuccess: onClose });
  return (
    <Dialog open title={`Verify call-back – ${number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Confirm you called {supplier.legal_name} on an independently sourced number and the account holder and IFSC were confirmed.</p>
      <Field label="Call-back note (required)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Called registered landline; holder name and IFSC confirmed by accounts head" />}</Field>
      <Actions onClose={onClose}><Button variant="primary" disabled={!note.trim()} busy={verify.isPending} onClick={() => verify.mutate()}>Verify call-back</Button></Actions>
    </Dialog>
  );
}

function UnblockDialog({ supplier, onClose }: { supplier: Supplier360; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const unblock = useCommand(() => api.post<{ status: string; paymentBlockLifted: string[] }>(`/suppliers/${encodeURIComponent(supplier.code)}/unblock`, { reason: reason.trim() }), {
    success: (r) => `${supplier.code} is ${label(r.status).toLowerCase()} again${r.paymentBlockLifted.length ? ` · payment block lifted on ${r.paymentBlockLifted.join(', ')}` : ''}`, onSuccess: onClose });
  return (
    <Dialog open title={`Unblock ${supplier.code}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-700">Restores the status before the block and lifts the payment blocks the block set on posted invoices. A sanctions match must be re-screened clear first.</p>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Alert closed as a false positive after the compliance review" />}</Field>
      <Actions onClose={onClose}><Button variant="primary" disabled={reason.trim().length < 3} busy={unblock.isPending} onClick={() => unblock.mutate()}>Unblock supplier</Button></Actions>
    </Dialog>
  );
}

function BankChangeDialog({ supplier, onClose }: { supplier: Supplier360; onClose: () => void }) {
  const [account, setAccount] = useState('');
  const [ifsc, setIfsc] = useState('');
  const [holder, setHolder] = useState(supplier.legal_name);
  const accountOk = /^[0-9]{9,18}$/.test(account);
  const ifscOk = /^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc);
  const request = useCommand(() => api.post<{ number: string }>(`/suppliers/${encodeURIComponent(supplier.code)}/bank-changes`, {
    bank_account: account, ifsc, holder_name: holder.trim() }), {
    success: (r) => `${r.number} requested – another supplier manager verifies the call-back, then two finance controllers approve`, onSuccess: onClose });
  return (
    <Dialog open title={`Request bank change – ${supplier.code}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">MDM-04: the new account is used only after an independent call-back, approval by two different finance controllers and the cooling-off period. You cannot verify or approve your own request.</p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Account number" hint={account && !accountOk ? '9–18 digits' : undefined}>{(id) => <Input id={id} inputMode="numeric" autoComplete="off" value={account} onChange={(e) => setAccount(e.target.value.replace(/\s/g, ''))} />}</Field>
        <Field label="IFSC" hint={ifsc && !ifscOk ? 'e.g. SBIN0001234' : undefined}>{(id) => <Input id={id} value={ifsc} onChange={(e) => setIfsc(e.target.value.toUpperCase().trim())} maxLength={11} />}</Field>
        <div className="md:col-span-2"><Field label="Account holder">{(id) => <Input id={id} value={holder} onChange={(e) => setHolder(e.target.value)} />}</Field></div>
      </div>
      <Actions onClose={onClose}><Button variant="primary" disabled={!accountOk || !ifscOk || holder.trim().length < 3} busy={request.isPending} onClick={() => request.mutate()}>Request change</Button></Actions>
    </Dialog>
  );
}

function ScreeningDialog({ supplier, review, onClose }: { supplier: Supplier360; review: boolean; onClose: () => void }) {
  const duplicates = supplier.screening?.duplicates ?? [];
  const [decision, setDecision] = useState(review ? 'CLEAR' : 'RESCREEN');
  const [note, setNote] = useState('');
  const [mergeInto, setMergeInto] = useState(duplicates[0]?.code ?? '');
  const options = review
    ? [{ value: 'CLEAR', label: 'Clear – not a duplicate / provider outage checked manually' },
      ...(duplicates.length ? [{ value: 'MERGE', label: 'Merge – this registration duplicates an existing supplier' }] : []),
      { value: 'RESCREEN', label: 'Re-screen – run duplicate and sanctions checks again' }]
    : [{ value: 'RESCREEN', label: 'Re-screen – run duplicate and sanctions checks again' }];
  const dispose = useCommand(() => api.post<{ screening: { outcome: string } }>(`/suppliers/${encodeURIComponent(supplier.code)}/screening-disposition`, {
    decision, note: note.trim(), merge_into: decision === 'MERGE' ? mergeInto : undefined }), {
    success: (r) => decision === 'RESCREEN' ? `Re-screened · ${label(r.screening.outcome)}` : decision === 'MERGE' ? `${supplier.code} merged into ${mergeInto}` : 'Screening review cleared',
    onSuccess: onClose });
  return (
    <Dialog open title={`Screening – ${supplier.code}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Outcome {label(supplier.screening?.outcome ?? 'not screened')} · {dateTime(supplier.screening?.screenedAt)}. Clearing or merging is recorded in the audit trail and cannot be done by the person who registered the supplier.</p>
      <div className="grid gap-3">
        <Field label="Decision">{(id) => <Select id={id} value={decision} onChange={(e) => setDecision(e.target.value)} options={options} />}</Field>
        {decision === 'MERGE' && (
          <Field label="Merge into">{(id) => <Select id={id} value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}
            options={duplicates.map((d) => ({ value: d.code, label: `${d.code} – ${d.reason}` }))} />}</Field>
        )}
        <Field label="Note (required)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Different PAN and GSTIN; MCA records checked; unrelated entity" />}</Field>
      </div>
      <Actions onClose={onClose}><Button variant="primary" disabled={note.trim().length < 3 || (decision === 'MERGE' && !mergeInto)} busy={dispose.isPending} onClick={() => dispose.mutate()}>Record</Button></Actions>
    </Dialog>
  );
}

function VerifyCertificateDialog({ cert, onClose }: { cert?: Certificate; onClose: () => void }) {
  const [note, setNote] = useState('');
  const verify = useCommand(() => api.post(`/certificates/${cert?.id}/verify`, { note: note.trim() }),
    { success: `Certificate ${cert?.type ?? ''} ${cert?.number ?? ''} verified`, onSuccess: onClose });
  if (!cert) return null;
  return (
    <Dialog open title={`Verify certificate – ${cert.type}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{cert.number} · issued {date(cert.issued_on)} · expires {date(cert.expires_on)}. Check it against the issuing body&apos;s register or the original; the person who uploaded it cannot verify it.</p>
      <Field label="How was it verified? (required)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. IATF database checked, certificate active" />}</Field>
      <Actions onClose={onClose}><Button variant="primary" disabled={note.trim().length < 3} busy={verify.isPending} onClick={() => verify.mutate()}>Verify certificate</Button></Actions>
    </Dialog>
  );
}

function BlockDialog({ supplier, onClose }: { supplier: Supplier360; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState('');
  const block = useCommand(() => api.post<{ openPosFlagged: string[] }>(`/suppliers/${encodeURIComponent(supplier.code)}/block`, { reason: reason.trim() }), {
    success: (r) => `${supplier.code} blocked${r.openPosFlagged.length ? ` – ${r.openPosFlagged.length} open PO(s) flagged for buyer review` : ''}`, onSuccess: onClose });
  return (
    <Dialog open title={`Block ${supplier.code}`} onClose={onClose}>
      {!confirming ? (
        <>
          <p className="mb-3 text-sm text-slate-700">Blocking sets every category of {supplier.legal_name} to Blocked: the supplier can no longer be invited, awarded or ordered from, cannot submit invoices and is not paid (its unpaid invoices get a payment block). Open purchase orders are flagged to their buyers for review.</p>
          <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Sanctions screening hit / repeated quality escapes" />}</Field>
          <Actions onClose={onClose}><Button variant="danger" disabled={!reason.trim()} onClick={() => setConfirming(true)}>Continue</Button></Actions>
        </>
      ) : (
        <>
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
            <p className="font-semibold">Confirm blocking {supplier.legal_name}</p>
            <p className="mt-0.5">Reason: {reason}</p>
          </div>
          <div className="mt-3">
            <Field label={`Type the supplier code ${supplier.code} to confirm`}>{(id) => <Input id={id} value={typed} onChange={(e) => setTyped(e.target.value.toUpperCase())} autoComplete="off" />}</Field>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={() => setConfirming(false)}>Back</Button>
            <Button variant="danger" disabled={typed !== supplier.code} busy={block.isPending} onClick={() => block.mutate()}>Block supplier</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}
