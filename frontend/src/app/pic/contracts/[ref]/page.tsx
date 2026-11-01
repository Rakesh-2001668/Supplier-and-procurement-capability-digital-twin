'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ReactNode, useMemo, useState, useSyncExternalStore } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Dialog, Empty, Facts, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, readSessionUser, SessionUser } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { AmendKind, AmendmentDialog, AmendmentsTab, AmendmentSummary, useAmendmentRule } from './_amendments';
import { ExtractionTab } from './_extraction';
import { RebatesTab } from './_rebates';
import { ClauseReviewTab, PendingRedline, PositionChip } from './_clauses';

type ContractLine = { id: string; line_no: number; description: string; plant: string; uom: string; target_qty: string; released_qty: string;
  released_value_minor: number };
type PriceValidity = { id: string; contract_line_id: string; valid_from: string; valid_to: string; unit_price_minor: number; index_value: string | null;
  reason: string; published: boolean };
type Clause = { id: string; code: string; title: string; text: string; position: string; risk_score: number };
type Signature = { id: string; party: string; signer_name: string; signed_at: string; envelope_ref: string; provider?: string; demoSignature?: boolean; label?: string | null };
type IndexRef = { index: string; base: string; band_pct: string; reset?: string };
type Contract = {
  id: string; number: string; type: string; title: string; status: string; supplier: { id: string; code: string; name: string };
  company_code: string; valid_from: string; valid_to: string; payment_terms: string; incoterms: string | null; over_tolerance_pct: string;
  under_tolerance_pct: string; price_tolerance_pct: string; target_value_minor: number; index_ref: IndexRef | null; source_event_id: string | null;
  thresholds_hit: number[] | null; rule_set_version: string; activated_at: string | null; version: number;
  terminated_at: string | null; termination_reason: string | null; framework_contract_id: string | null; jurisdiction: string | null;
  lines: ContractLine[]; priceValidity: PriceValidity[]; clauses: Clause[]; signatures: Signature[]; pendingRedlines?: PendingRedline[];
  demoSignature?: boolean;
};
type Brief = { number: string; title: string; type: string; status: string; validFrom: string; validTo: string; targetValueMinor: number };
type Framework = { contract: string; type: string; jurisdiction: string | null; framework: Brief | null; callOffs: Brief[] };
type Review = { risk: number; riskBand?: string; findings: { clause: string; position: string; risk: number; fallback: string | null; textDeviates?: boolean;
  suggestedPosition?: string | null }[]; aiRef: string };
type Consumption = { contract: string; status: string; thresholdsHit: number[] | null;
  lines: { line: number; description: string; targetQty: string; releasedQty: string; releasedValueMinor: number; consumedPct: string; thresholdsHit?: number[];
    currentPriceMinor: number | null; offContract: { po: string; line: number; qty: string; unitPriceMinor: number; valueMinor?: number; leakageMinor: number }[];
    priceDeviations?: { po: string; line: number; qty: string; unitPriceMinor: number; contractPriceMinor: number; excessMinor: number; reason: string | null }[] }[];
  compliance?: { targetValueMinor: number; releasedValueMinor: number; consumedValuePct: string; offContractValueMinor: number; priceLeakageMinor: number;
    offContractLines: number; priceDeviationLines: number; complianceRatePct: string | null; definition: string };
  obligations: { id: string; party: string; kind?: string; description: string; dueDate: string; status: string; completedAt?: string | null }[] };
type IndexResult = { contract: string; changePct: string; adjustPct: string; lines: { line: number; oldPriceMinor: number; newPriceMinor: number }[] };

const REVIEWABLE = ['DRAFT', 'IN_NEGOTIATION'];
const noSubscribe = () => () => {};
const AMENDABLE = ['ACTIVE', 'EXPIRING'];

export default function ContractPage() {
  const { ref } = useParams<{ ref: string }>();
  const path = `/contracts/${encodeURIComponent(ref)}`;
  const { data: c, isLoading, error } = useApi<Contract>(path);
  // Session user from the cookie; not available while rendering on the server.
  const cookie = useSyncExternalStore(noSubscribe, () => document.cookie, () => null);
  const ready = cookie !== null;
  const user = useMemo<SessionUser | null>(() => (cookie === null ? null : readSessionUser()), [cookie]);
  const manager = ready && (!user || user.roles.includes('CONTRACT_MANAGER'));
  const [dialog, setDialog] = useState<'sign' | 'index' | null>(null);
  const [reviewing, setReviewing] = useState<PendingRedline | null>(null);
  const [amend, setAmend] = useState<AmendKind | null>(null);
  const amendRule = useAmendmentRule(c && AMENDABLE.includes(c.status) ? c.number : undefined);
  const [review, setReview] = useState<Review | null>(null);

  const runReview = useCommand(() => api.post<Review>(`${path}/review`), {
    success: (r) => `AI review complete – contract risk ${r.risk}, ${r.findings.length} deviation(s)`, onSuccess: setReview });
  const submit = useCommand(() => api.post<{ status: string; chain: string[] }>(`${path}/submit`), {
    success: (r) => `Submitted for approval: ${r.chain.map(label).join(' → ')}` });
  const activate = useCommand(() => api.post(`${path}/activate`), { success: 'Contract active – price validity published to source determination' });
  const envelope = useCommand(() => api.post<{ provider: string; envelopeId: string }>(`${path}/signature-envelopes`, {}), {
    success: (r) => `Sent to ${label(r.provider)} for e-signature – envelope ${r.envelopeId}; signatures are recorded when the signers complete` });

  const parties = new Set(c?.signatures.map((s) => s.party));
  const nonStandard = c?.clauses.filter((x) => x.position !== 'STANDARD').length ?? 0;
  const pending = c?.pendingRedlines ?? [];

  return (
    <>
      <ObjectPage
        type="CONTRACT" docRef={ref} eyebrow={`CLM-01 · ${c ? label(c.type) : 'Contract'}`} loading={isLoading} error={error}
        title={<>{c?.number} <span className="text-base font-normal text-slate-500">{c?.title}</span></>}
        status={c?.status}
        actions={c && manager && (
          <>
            {REVIEWABLE.includes(c.status) && <Button busy={runReview.isPending} onClick={() => runReview.mutate()}>AI review</Button>}
            {c.status === 'IN_NEGOTIATION' && (
              <Button variant="primary" busy={submit.isPending} disabled={pending.length > 0} onClick={() => submit.mutate()}
                title={pending.length ? `Review the supplier redline(s) on ${pending.map((r) => r.clause).join(', ')} first` : undefined}>Submit for approval</Button>
            )}
            {c.status === 'OUT_FOR_SIGNATURE' && !parties.has('BUYER') && <Button variant="primary" onClick={() => setDialog('sign')}>Sign as buyer</Button>}
            {c.status === 'OUT_FOR_SIGNATURE' && !(parties.has('BUYER') && parties.has('SUPPLIER')) && (
              <Button busy={envelope.isPending} onClick={() => envelope.mutate()} title="Uses the configured e-signature provider (DocuSign, Adobe Sign, Leegality or eMudhra)">Send via e-sign provider</Button>
            )}
            {c.status === 'OUT_FOR_SIGNATURE' && (
              <Button variant={parties.has('BUYER') ? 'primary' : 'secondary'} busy={activate.isPending} disabled={!(parties.has('BUYER') && parties.has('SUPPLIER'))}
                title={!(parties.has('BUYER') && parties.has('SUPPLIER')) ? 'Both buyer and supplier must sign first' : undefined}
                onClick={() => activate.mutate()}>Activate</Button>
            )}
            {['ACTIVE', 'EXPIRING'].includes(c.status) && c.index_ref && <Button onClick={() => setDialog('index')}>Index reset</Button>}
            {AMENDABLE.includes(c.status) && <Button onClick={() => setAmend('VARIATION')}>Amend</Button>}
            {AMENDABLE.includes(c.status) && <Button variant="danger" onClick={() => setAmend('TERMINATION')}>Terminate</Button>}
          </>
        )}
        facts={c && (
          <div className="space-y-4">
            <Facts items={[
              ['Supplier', <Link key="s" href={`/pic/suppliers/${encodeURIComponent(c.supplier.code)}`} className="text-[#1A56DB] hover:underline">{c.supplier.name} ({c.supplier.code})</Link>],
              ['Type', label(c.type)],
              ['Validity', `${date(c.valid_from)} – ${date(c.valid_to)}`],
              ['Target value', inr(c.target_value_minor)],
              ['Payment terms', c.payment_terms],
              ['Incoterms', c.incoterms ?? '–'],
              ['Tolerances', `qty +${c.over_tolerance_pct}% / −${c.under_tolerance_pct}% · price ±${c.price_tolerance_pct}%`],
              ['Price index', c.index_ref ? `${c.index_ref.index} base ${c.index_ref.base} · band ±${c.index_ref.band_pct}%${c.index_ref.reset ? ` · ${label(c.index_ref.reset)}` : ''}` : 'not indexed'],
              ['Consumption alerts', c.thresholds_hit?.length ? c.thresholds_hit.map((t) => `${t}% reached`).join(', ') : 'none'],
              ['Company code', c.company_code],
              ['Governing-law variant', c.jurisdiction ?? 'playbook default'],
              ...(c.framework_contract_id || c.type === 'MASTER_AGREEMENT' ? [['Framework', <FrameworkLink key="fw" number={c.number} />] as [string, ReactNode]] : []),
              ['Activated', dateTime(c.activated_at)],
              ['Playbook', <span key="p" className="font-mono text-xs">{c.rule_set_version}</span>],
              ['Version', `v${c.version ?? 1}`],
              ...(c.terminated_at ? [['Terminated', `${dateTime(c.terminated_at)} – ${c.termination_reason ?? ''}`] as [string, string]] : []),
            ]} />
            {AMENDABLE.includes(c.status) && <AmendmentSummary contractNumber={c.number} />}
            {review && <ReviewPanel review={review} />}
            {pending.length > 0 && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {pending.length} supplier redline(s) wait for your review ({pending.map((r) => r.clause).join(', ')}): accept with a playbook position or
                restore the original text in the Clauses tab. Until then the clause counts as non-standard and the contract cannot be submitted.
              </p>
            )}
            {c.demoSignature && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                Demo signature – not legally binding. At least one signature of this contract came from the MOCK e-signature provider (demo and test use only).
              </p>
            )}
            {c.status === 'OUT_FOR_SIGNATURE' && (
              <p className="text-sm text-slate-600">Signatures: buyer {parties.has('BUYER') ? '✓ signed' : '– pending'} · supplier {parties.has('SUPPLIER') ? '✓ signed' : '– pending (signs in the supplier portal)'}.</p>
            )}
          </div>
        )}
        lines={c && <LinesWithValidity contract={c} />}
        extraTabs={c ? [
          {
            id: 'clauses', label: `Clauses (${c.clauses.length}${nonStandard ? `, ${nonStandard} deviating` : ''}${pending.length ? `, ${pending.length} to review` : ''})`, content: (
              <ClauseReviewTab key={`${c.version}-${c.clauses.map((x) => `${x.position}${x.risk_score}${x.text.length}`).join('')}`} contractNumber={c.number}
                status={c.status} canManage={manager} onReview={setReviewing} />
            ),
          },
          {
            id: 'signatures', label: `Signatures (${c.signatures.length})`, content: (
              <DataTable<Signature> rows={c.signatures} empty="Not signed yet" columns={[
                { key: 'party', header: 'Party', render: (s) => label(s.party) },
                { key: 'signer_name', header: 'Signer' },
                { key: 'signed_at', header: 'Signed', render: (s) => dateTime(s.signed_at) },
                { key: 'envelope_ref', header: 'E-sign envelope', render: (s) => <span className="font-mono text-xs">{s.envelope_ref}</span> },
                { key: 'provider', header: 'Provider', render: (s) => (s.demoSignature
                  ? <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900" title="Signed through the MOCK e-signature provider">Demo signature – not legally binding</span>
                  : <span className="text-xs text-slate-600">{label(s.provider ?? 'INTERNAL')}</span>) },
              ]} />
            ),
          },
          ...(c.type === 'MASTER_AGREEMENT' || c.framework_contract_id ? [{ id: 'framework', label: c.type === 'MASTER_AGREEMENT' ? 'Call-off contracts' : 'Framework', content: <FrameworkTab number={c.number} /> }] : []),
          { id: 'consumption', label: 'Consumption & obligations', content: <ConsumptionTab path={path} canManage={manager} /> },
          ...(c.type !== 'NDA' ? [{ id: 'rebates', label: 'Rebates', content: <RebatesTab contractNumber={c.number} contractType={c.type} contractStatus={c.status}
            validFrom={c.valid_from} validTo={c.valid_to} canManage={manager} /> }] : []),
          { id: 'extraction', label: 'Clause extraction', content: <ExtractionTab contractNumber={c.number} canManage={manager} /> },
          { id: 'amendments', label: `Amendments (v${c.version ?? 1})`, content: <AmendmentsTab contract={c} canManage={manager} /> },
        ] : []}
      />
      {c && dialog === 'sign' && <SignDialog contract={c} defaultName={user ? `${user.name}` : ''} onClose={() => setDialog(null)} />}
      {c && dialog === 'index' && c.index_ref && <IndexResetDialog contract={c} indexRef={c.index_ref} onClose={() => setDialog(null)} />}
      {c && reviewing && <RedlineReviewDialog contract={c} redline={reviewing} onClose={() => setReviewing(null)} />}
      {c && amend && <AmendmentDialog contract={c} initialKind={amend} noticeDays={amendRule?.noticeDays} onClose={() => setAmend(null)} />}
    </>
  );
}

const POSITIONS = ['STANDARD', 'FALLBACK', 'NON_STANDARD'];

/** The master agreement a call-off refers to (one line in the facts), or how many call-offs a master agreement has. */
function FrameworkLink({ number }: { number: string }) {
  const { data } = useApi<Framework>(`/contracts/${encodeURIComponent(number)}/framework`);
  if (!data) return <span>…</span>;
  if (data.framework) return <Link href={`/pic/contracts/${encodeURIComponent(data.framework.number)}`} className="text-[#1A56DB] hover:underline">{data.framework.number}</Link>;
  return <span>{data.callOffs.length} call-off contract(s)</span>;
}

/** CLM framework: the master agreement of a call-off contract, or the call-off contracts of a master agreement. */
function FrameworkTab({ number }: { number: string }) {
  const { data, isLoading, error } = useApi<Framework>(`/contracts/${encodeURIComponent(number)}/framework`);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  const rows = data.framework ? [data.framework] : data.callOffs;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        {data.framework ? 'This contract is a call-off of the master agreement below. Its period must stay inside the master agreement, which cannot be terminated while call-offs are live.'
          : 'Call-off contracts refer to this master agreement for their commercial terms. It cannot be terminated while a call-off is active.'}
      </p>
      <DataTable<Brief & Record<string, unknown>> rows={rows} empty="No call-off contracts yet" rowHref={(b) => `/pic/contracts/${encodeURIComponent(b.number)}`} columns={[
        { key: 'number', header: 'Contract' },
        { key: 'title', header: 'Title' },
        { key: 'type', header: 'Type', render: (b) => label(b.type) },
        { key: 'status', header: 'Status', render: (b) => <StatusChip status={b.status} /> },
        { key: 'validFrom', header: 'Validity', render: (b) => `${date(b.validFrom)} – ${date(b.validTo)}` },
        { key: 'targetValueMinor', header: 'Target value', align: 'right', render: (b) => inr(b.targetValueMinor) },
      ]} />
    </div>
  );
}

/** CLM-REDLINE: the contract manager classifies the supplier's text (NON_STANDARD routes the approval through LEGAL) or restores the text it replaced. */
function RedlineReviewDialog({ contract, redline, onClose }: { contract: Contract; redline: PendingRedline; onClose: () => void }) {
  const clause = contract.clauses.find((x) => x.code === redline.clause);
  const [decision, setDecision] = useState<'ACCEPT' | 'RESTORE'>('ACCEPT');
  const [position, setPosition] = useState('NON_STANDARD');
  const [comment, setComment] = useState('');
  const go = useCommand(() => api.post<{ code: string; position: string }>(
    `/contracts/${encodeURIComponent(contract.number)}/redlines/${encodeURIComponent(redline.clause)}/review`,
    { decision, position: decision === 'ACCEPT' ? position : undefined, comment: comment.trim() || undefined }), {
    success: (r) => (decision === 'ACCEPT' ? `Redline on ${r.code} accepted as ${label(r.position)}` : `Original text of ${r.code} restored`), onSuccess: onClose,
  });
  return (
    <Dialog open title={`Review supplier redline · ${redline.clause}`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div className="rounded-lg bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Supplier text ({redline.by}, {dateTime(redline.at)})</p>
          <p className="mt-1 text-slate-800">{clause?.text ?? redline.proposedText}</p>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Text it replaced ({label(redline.originalPosition ?? 'STANDARD')})</p>
          <p className="mt-1 text-slate-700">{redline.originalText ?? '–'}</p>
        </div>
        <fieldset className="space-y-1">
          <legend className="text-xs font-semibold uppercase text-slate-500">Decision</legend>
          <label className="flex items-center gap-2"><input type="radio" name="decision" checked={decision === 'ACCEPT'} onChange={() => setDecision('ACCEPT')} />
            Accept the supplier text</label>
          <label className="flex items-center gap-2"><input type="radio" name="decision" checked={decision === 'RESTORE'} onChange={() => setDecision('RESTORE')} />
            Restore the replaced text</label>
        </fieldset>
        {decision === 'ACCEPT' && (
          <Field label="Position against the playbook" hint="Non-standard routes the contract approval through Legal">
            {(id) => (
              <Select id={id} value={position} onChange={(e) => setPosition(e.target.value)} options={POSITIONS.map((p) => ({ value: p, label: label(p) }))} />
            )}
          </Field>
        )}
        <Field label="Comment (recorded in the audit trail)">{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={go.isPending} onClick={() => go.mutate()}>{decision === 'ACCEPT' ? 'Accept redline' : 'Restore text'}</Button>
      </div>
    </Dialog>
  );
}

function ReviewPanel({ review }: { review: Review }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3 text-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">AI contract review (explainable)</p>
      <p className="mt-1">Contract risk <span className="font-semibold">{review.risk}/100{review.riskBand ? ` (${review.riskBand.toLowerCase()})` : ''}</span> · {review.findings.length ? `${review.findings.length} clause(s) deviate from the playbook` : 'all clauses on standard playbook positions'}</p>
      {review.findings.length > 0 && (
        <ul className="mt-1 space-y-1">
          {review.findings.map((f) => (
            <li key={f.clause}><span className="font-mono text-xs">{f.clause}</span> · <PositionChip position={f.position} /> risk {f.risk}{f.textDeviates ? ' · wording changed from the library' : ''}{f.fallback ? <> — playbook fallback: <span className="italic">{f.fallback}</span></> : null}{f.suggestedPosition ? <> · suggested position {label(f.suggestedPosition)}</> : null}</li>
          ))}
        </ul>
      )}
      <p className="mt-1 font-mono text-[11px] text-slate-400">{review.aiRef}</p>
    </div>
  );
}

function LinesWithValidity({ contract }: { contract: Contract }) {
  if (!contract.lines.length) return <Empty title="No contract lines" />;
  return (
    <div className="space-y-4">
      {contract.lines.map((l) => {
        const periods = contract.priceValidity.filter((p) => p.contract_line_id === l.id);
        const consumed = Number(l.target_qty) ? (Number(l.released_qty) / Number(l.target_qty)) * 100 : 0;
        return (
          <div key={l.id} className="rounded-lg border border-slate-200">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-100 px-4 py-2">
              <p className="text-sm"><span className="font-mono text-xs text-slate-500">Line {l.line_no}</span> <span className="font-semibold">{l.description}</span> <span className="text-slate-500">· {l.plant}</span></p>
              <p className="text-sm text-slate-600">Target {qty(l.target_qty, l.uom)} · released {qty(l.released_qty)} ({consumed.toFixed(1)}%) · {inr(l.released_value_minor)}</p>
            </div>
            <div className="p-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Price validity periods</p>
              <DataTable<PriceValidity> rows={periods} empty="No price periods" columns={[
                { key: 'valid_from', header: 'Valid from', render: (p) => date(p.valid_from) },
                { key: 'valid_to', header: 'Valid to', render: (p) => date(p.valid_to) },
                { key: 'unit_price_minor', header: 'Unit price', align: 'right', render: (p) => inr(p.unit_price_minor) },
                { key: 'index_value', header: 'Index value', align: 'right', render: (p) => p.index_value ?? '–' },
                { key: 'reason', header: 'Reason', render: (p) => label(p.reason) },
                { key: 'published', header: 'Published', render: (p) => (p.published ? 'Yes – used by source determination' : 'No (until activation)') },
              ]} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConsumptionTab({ path, canManage }: { path: string; canManage: boolean }) {
  const { data, isLoading, error } = useApi<Consumption>(`${path}/consumption`);
  const [done, setDone] = useState<{ id: string; description: string } | null>(null);
  const [adding, setAdding] = useState(false);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data) return null;
  const leakage = data.lines.flatMap((l) => l.offContract.map((o) => ({ ...o, id: `${o.po}-${o.line}`, item: l.description })));
  const priceDeviations = data.lines.flatMap((l) => l.priceDeviations ?? []);
  return (
    <div className="space-y-5">
      <div className="space-y-3">
        {data.lines.map((l) => {
          const pctValue = Math.min(100, Number(l.consumedPct));
          return (
            <div key={l.line}>
              <div className="flex flex-wrap justify-between gap-2 text-sm">
                <span><span className="font-mono text-xs text-slate-500">Line {l.line}</span> {l.description}</span>
                <span className="tabular-nums text-slate-700">{qty(l.releasedQty)} of {qty(l.targetQty)} · <span className="font-semibold">{l.consumedPct}% consumed</span>{l.thresholdsHit?.length ? ` (alerts ${l.thresholdsHit.join('/')}%)` : ''} · current price {inr(l.currentPriceMinor)}</span>
              </div>
              <div className="mt-1 h-2 rounded-full bg-slate-100" role="progressbar" aria-valuenow={pctValue} aria-valuemin={0} aria-valuemax={100} aria-label={`Line ${l.line} consumption`}>
                <div className="h-2 rounded-full bg-[#1A56DB]" style={{ width: `${pctValue}%` }} />
              </div>
            </div>
          );
        })}
        <p className="text-xs text-slate-500">Alerts fire at the configured consumption thresholds{data.thresholdsHit?.length ? ` – reached: ${data.thresholdsHit.join('%, ')}%` : ''}.</p>
      </div>

      {data.compliance && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Compliance rate', data.compliance.complianceRatePct ? `${data.compliance.complianceRatePct}%` : '–', 'released on contract / (released + bought off-contract)'],
            ['Released value', inr(data.compliance.releasedValueMinor), `${data.compliance.consumedValuePct}% of ${inr(data.compliance.targetValueMinor)}`],
            ['Off-contract buying', inr(data.compliance.offContractValueMinor), `${data.compliance.offContractLines} PO line(s) outside the contract`],
            ['Price leakage', inr(data.compliance.priceLeakageMinor), `${data.compliance.priceDeviationLines} flagged contract-priced line(s) plus off-contract above contract price`],
          ].map(([k, v, hint]) => (
            <div key={k} className="rounded-lg border border-slate-200 p-3"><p className="text-xs uppercase tracking-wide text-slate-500">{k}</p>
              <p className="text-lg font-semibold tabular-nums">{v}</p><p className="text-xs text-slate-500">{hint}</p></div>
          ))}
        </div>
      )}

      {priceDeviations.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Orders priced outside the contract tolerance (flagged)</h3>
          <DataTable<(typeof priceDeviations)[number]> rows={priceDeviations} columns={[
            { key: 'po', header: 'PO', render: (o) => <Link href={`/pic/purchase-orders/${encodeURIComponent(o.po)}`} className="font-medium text-[#1A56DB] hover:underline">{o.po} / {o.line}</Link> },
            { key: 'qty', header: 'Qty', align: 'right', render: (o) => qty(o.qty) },
            { key: 'contractPriceMinor', header: 'Contract price', align: 'right', render: (o) => inr(o.contractPriceMinor) },
            { key: 'unitPriceMinor', header: 'Ordered at', align: 'right', render: (o) => inr(o.unitPriceMinor) },
            { key: 'excessMinor', header: 'Excess', align: 'right', render: (o) => <span className="font-semibold text-red-700">{inr(o.excessMinor)}</span> },
            { key: 'reason', header: 'Reason given', render: (o) => o.reason ?? '–' },
          ]} />
        </div>
      )}

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Off-contract leakage</h3>
        <DataTable<(typeof leakage)[number]> rows={leakage} empty="No off-contract purchases of the contracted items since validity start" columns={[
          { key: 'po', header: 'PO', render: (o) => <Link href={`/pic/purchase-orders/${encodeURIComponent(o.po)}`} className="font-medium text-[#1A56DB] hover:underline">{o.po} / {o.line}</Link> },
          { key: 'item', header: 'Item' },
          { key: 'qty', header: 'Qty', align: 'right', render: (o) => qty(o.qty) },
          { key: 'unitPriceMinor', header: 'Paid / unit', align: 'right', render: (o) => inr(o.unitPriceMinor) },
          { key: 'leakageMinor', header: 'Leakage vs contract', align: 'right', render: (o) => <span className={o.leakageMinor > 0 ? 'font-semibold text-red-700' : ''}>{inr(o.leakageMinor)}</span> },
        ]} />
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Obligations and milestones</h3>
          {canManage && !['EXPIRED', 'TERMINATED', 'RENEWED'].includes(data.status) && <Button onClick={() => setAdding(true)}>Add obligation</Button>}
        </div>
        <DataTable<Consumption['obligations'][number]> rows={data.obligations} empty="No obligations" columns={[
          { key: 'description', header: 'Obligation', render: (o) => <span>{o.kind === 'MILESTONE' ? <span className="mr-1 text-[11px] font-semibold uppercase text-slate-500">milestone</span> : null}{o.description}</span> },
          { key: 'party', header: 'Party', render: (o) => label(o.party) },
          { key: 'dueDate', header: 'Due', render: (o) => {
            const overdue = o.status === 'OPEN' && new Date(o.dueDate) < new Date();
            return <span className={overdue ? 'font-semibold text-red-700' : ''}>{date(o.dueDate)}{overdue ? ' (overdue)' : ''}</span>;
          } },
          { key: 'status', header: 'Status', render: (o) => <StatusChip status={o.status === 'DONE' ? 'COMPLETED' : o.status} /> },
          { key: 'action', header: '', render: (o) => (canManage && o.status === 'OPEN' ? <Button onClick={() => setDone({ id: o.id, description: o.description })}>Mark done</Button> : null) },
        ]} />
      </div>
      {done && <ObligationDialog obligation={done} onClose={() => setDone(null)} />}
      {adding && <AddObligationDialog contractNumber={data.contract} onClose={() => setAdding(false)} />}
    </div>
  );
}

function AddObligationDialog({ contractNumber, onClose }: { contractNumber: string; onClose: () => void }) {
  const [party, setParty] = useState('SUPPLIER');
  const [kind, setKind] = useState('OBLIGATION');
  const [description, setDescription] = useState('');
  const [due, setDue] = useState('');
  const [key] = useState(() => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`));
  const add = useCommand(() => api.post(`/contracts/${encodeURIComponent(contractNumber)}/obligations`, { party, kind, description: description.trim(), due_date: due },
    { idempotencyKey: key }), { success: 'Obligation added', onSuccess: onClose });
  return (
    <Dialog open title={`Add obligation · ${contractNumber}`} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Party">{(id) => <Select id={id} value={party} onChange={(e) => setParty(e.target.value)} options={[{ value: 'SUPPLIER', label: 'Supplier' }, { value: 'BUYER', label: 'Buyer (us)' }]} />}</Field>
          <Field label="Type">{(id) => <Select id={id} value={kind} onChange={(e) => setKind(e.target.value)} options={[{ value: 'OBLIGATION', label: 'Obligation' }, { value: 'MILESTONE', label: 'Milestone' }]} />}</Field>
        </div>
        <Field label="Description (at least 3 characters)">{(id) => <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
        <Field label="Due date">{(id) => <Input id={id} type="date" value={due} onChange={(e) => setDue(e.target.value)} />}</Field>
        <ProblemBox error={add.error} />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={description.trim().length < 3 || !due} busy={add.isPending} onClick={() => add.mutate()}>Add</Button>
      </div>
    </Dialog>
  );
}

function ObligationDialog({ obligation, onClose }: { obligation: { id: string; description: string }; onClose: () => void }) {
  const [note, setNote] = useState('');
  const complete = useCommand(() => api.post(`/obligations/${obligation.id}/complete`, { note: note.trim() }), { success: 'Obligation marked done', onSuccess: onClose });
  return (
    <Dialog open title="Mark obligation done" onClose={onClose}>
      <p className="mb-3 text-sm text-slate-700">{obligation.description}</p>
      <Field label="Evidence / note (required)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Forecast shared by e-mail on …" />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={note.trim().length < 3} busy={complete.isPending} onClick={() => complete.mutate()}>Mark done</Button>
      </div>
    </Dialog>
  );
}

function SignDialog({ contract, defaultName, onClose }: { contract: Contract; defaultName: string; onClose: () => void }) {
  const [name, setName] = useState(defaultName);
  const sign = useCommand(() => api.post<{ signedBy: string[] }>(`/contracts/${encodeURIComponent(contract.number)}/signatures`, { party: 'BUYER', signer_name: name.trim() }),
    { success: (r) => `Signed – signatures so far: ${r.signedBy.map(label).join(', ')}`, onSuccess: onClose });
  return (
    <Dialog open title={`Sign ${contract.number} as buyer`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">Your e-signature is bound to a hash of the current contract text, clauses and quantities. If anything changes later, activation is blocked until both parties re-sign.</p>
      <Field label="Signer name and designation">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ganesh Murthy, Contract Manager" />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!name.trim()} busy={sign.isPending} onClick={() => sign.mutate()}>Sign</Button>
      </div>
    </Dialog>
  );
}

function nextQuarterStart() {
  const d = new Date();
  const month = Math.floor(d.getMonth() / 3) * 3 + 3;
  const start = new Date(d.getFullYear() + Math.floor(month / 12), month % 12, 1);
  return `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-01`;
}

function IndexResetDialog({ contract, indexRef, onClose }: { contract: Contract; indexRef: IndexRef; onClose: () => void }) {
  const [value, setValue] = useState('');
  const [effective, setEffective] = useState(nextQuarterStart);
  const [result, setResult] = useState<IndexResult | null>(null);
  const reset = useCommand(() => api.post<IndexResult>(`/contracts/${encodeURIComponent(contract.number)}/index-resets`, { index_value: value, effective_from: effective }),
    { success: 'Index reset recorded as a new price validity period', onSuccess: setResult });
  const base = Number(indexRef.base);
  const band = Number(indexRef.band_pct);
  const v = Number(value);
  const valid = value !== '' && v > 0;
  const change = valid ? (v / base - 1) * 100 : 0;
  const adjust = Math.abs(change) <= band ? 0 : change > 0 ? change - band : change + band;
  const preview = contract.lines.map((l) => {
    const original = contract.priceValidity.filter((p) => p.contract_line_id === l.id).sort((a, b) => a.valid_from.localeCompare(b.valid_from))[0];
    const oldPrice = original?.unit_price_minor ?? 0;
    const newPrice = Math.round(oldPrice * (1 + adjust / 100));
    const market = Math.round(oldPrice * (1 + change / 100));
    const remaining = Number(l.target_qty) - Number(l.released_qty);
    const avoidance = change > 0 && contract.source_event_id ? (market - newPrice) * remaining : 0;
    return { line: l.line_no, description: l.description, oldPrice, newPrice, market, remaining, avoidance };
  });
  return (
    <Dialog open title={`Index reset – ${contract.number}`} onClose={onClose}>
      {result ? (
        <div className="space-y-3 text-sm">
          <p>Index moved <span className="font-semibold">{result.changePct}%</span>; price adjusted <span className="font-semibold">{result.adjustPct}%</span>{Number(result.adjustPct) === 0 ? ' (absorbed inside the band)' : ''}.</p>
          <ul className="space-y-1">{result.lines.map((l) => <li key={l.line}>Line {l.line}: {inr(l.oldPriceMinor)} → <span className="font-semibold">{inr(l.newPriceMinor)}</span></li>)}</ul>
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <>
          <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
            <p>The price follows <span className="font-semibold">{indexRef.index}</span> (base {indexRef.base}). Index changes within <span className="font-semibold">±{indexRef.band_pct}%</span> of the base are <span className="font-semibold">absorbed</span> by the supplier – the price stays unchanged. Beyond the band, only the excess over the band is passed through.</p>
            <p className="mt-1">Every reset creates a new price validity period from the effective date; history is never overwritten. When the index rises on an awarded contract, the difference between the market-indexed price and the agreed price on the remaining volume is booked as <span className="font-semibold">cost avoidance</span> in the savings register.</p>
          </div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <Field label={`New ${indexRef.index} index value`}>{(id) => <Input id={id} type="number" min="0" step="0.01" value={value} onChange={(e) => setValue(e.target.value)} placeholder={indexRef.base} />}</Field>
            <Field label="Effective from">{(id) => <Input id={id} type="date" value={effective} onChange={(e) => setEffective(e.target.value)} />}</Field>
          </div>
          {valid && (
            <div className="mt-3 text-sm">
              <p>Index change <span className="font-semibold">{change.toFixed(2)}%</span> → {adjust === 0 ? <span className="font-semibold text-emerald-700">absorbed (within ±{indexRef.band_pct}%)</span> : <span className="font-semibold text-amber-700">price adjusted {adjust.toFixed(2)}%</span>}</p>
              <table className="mt-2 min-w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr><th className="py-1">Line</th><th className="py-1 text-right">Current base</th><th className="py-1 text-right">Market-indexed</th><th className="py-1 text-right">New price</th><th className="py-1 text-right">Cost avoidance</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.map((p) => (
                    <tr key={p.line}>
                      <td className="py-1">{p.line} · {p.description}</td>
                      <td className="py-1 text-right tabular-nums">{inr(p.oldPrice)}</td>
                      <td className="py-1 text-right tabular-nums">{inr(p.market)}</td>
                      <td className="py-1 text-right font-semibold tabular-nums">{inr(p.newPrice)}</td>
                      <td className="py-1 text-right tabular-nums" title={`on remaining ${qty(p.remaining)}`}>{p.avoidance > 0 ? inr(p.avoidance) : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-xs text-slate-500">Preview; the server computes the authoritative values. Cost avoidance applies only to rises on contracts awarded from a sourcing event.</p>
            </div>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!valid || !effective} busy={reset.isPending} onClick={() => reset.mutate()}>Record index reset</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}
