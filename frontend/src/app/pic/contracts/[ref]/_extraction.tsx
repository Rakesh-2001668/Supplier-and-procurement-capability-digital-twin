'use client';

// Pending workflow 27 (TD §12.4): rule-based clause extraction from a contract text, reviewed by a person before the clauses reach the contract.

import { ChangeEvent, useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Item = {
  seq: number; code: string; title: string; heading: string | null; text: string; line: number; confidence: number; alternatives: { code: string; confidence: number }[];
  attributes: Record<string, unknown>; position: string; positionReason: string; risk: number; decision: 'PENDING' | 'ACCEPTED' | 'REJECTED'; edited?: boolean;
  reviewedBy?: string; reviewNote?: string;
};
type Unmatched = { heading: string | null; text: string; line: number; suggestions: string[]; confidence: number; note?: string };
type Discrepancy = { field: string; document: unknown; contract: unknown };
type Extraction = {
  id: string; number: string; source_name: string; contract_ref: string; status: 'EXTRACTED' | 'REVIEWED' | 'APPLIED' | 'REJECTED'; items: Item[]; unmatched: Unmatched[];
  attributes: { validFrom?: string; validTo?: string; autoRenewal?: boolean; parties?: string[]; contractValueMinor?: number; discrepancies?: Discrepancy[] };
  extractor_version: string; created_at: string; reviewed_at: string | null; applied_at: string | null;
  summary: { items: number; pending: number; accepted: number; lowConfidence: number; nonStandard: number };
};
type Decision = { action: 'ACCEPT' | 'EDIT' | 'REJECT'; text?: string; position?: string; code?: string };

const POSITIONS = ['STANDARD', 'FALLBACK', 'NON_STANDARD'];
const MAX_TEXT = 400_000;

export function ExtractionTab({ contractNumber, canManage }: { contractNumber: string; canManage: boolean }) {
  const list = useApi<Extraction[]>(canManage ? `/clause-extractions?contract=${encodeURIComponent(contractNumber)}` : null);
  const [selected, setSelected] = useState<string | null>(null);
  if (!canManage) return <Empty title="Clause extraction is for the contract manager" hint="Sign in as a contract manager to extract and review the clauses of a signed contract." />;
  if (selected) return <ExtractionReview number={selected} onBack={() => setSelected(null)} />;
  return (
    <div className="space-y-5">
      <NewExtraction contractNumber={contractNumber} onCreated={setSelected} />
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Extractions for this contract</h3>
        {list.isLoading ? <Loading /> : list.error ? <ProblemBox error={list.error} /> : (
          <DataTable<Extraction & Record<string, unknown>> rows={list.data ?? []} empty="Nothing extracted yet" columns={[
            { key: 'number', header: 'Extraction', render: (e) => <button className="font-medium text-[#1A56DB] hover:underline" onClick={() => setSelected(e.number)}>{e.number}</button> },
            { key: 'source_name', header: 'Source' },
            { key: 'status', header: 'Status', render: (e) => <StatusChip status={e.status === 'APPLIED' ? 'COMPLETED' : e.status === 'REVIEWED' ? 'READY' : e.status} /> },
            { key: 'summary', header: 'Clauses', render: (e) => `${e.summary.items} found · ${e.summary.pending} to review · ${e.summary.lowConfidence} low confidence` },
            { key: 'created_at', header: 'Extracted', render: (e) => dateTime(e.created_at) },
          ]} />
        )}
      </div>
    </div>
  );
}

function NewExtraction({ contractNumber, onCreated }: { contractNumber: string; onCreated: (number: string) => void }) {
  const [idempotencyKey, setKey] = useState(() => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`));
  const [text, setText] = useState('');
  const [source, setSource] = useState('');
  const [fileError, setFileError] = useState<string | null>(null);
  const create = useCommand(() => api.post<Extraction>('/clause-extractions', { contract: contractNumber, text, source_name: source.trim() || 'contract text' }, { idempotencyKey }),
    { success: (e) => `${e.number}: ${e.summary.items} clause(s) found, ${e.summary.pending} to review`, onSuccess: (e) => onCreated(e.number) });

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_TEXT) { setFileError(`The file is larger than ${MAX_TEXT.toLocaleString('en-IN')} characters; extract it in parts.`); return; }
    setFileError(null);
    setText(await file.text());
    setSource(file.name);
    setKey(crypto.randomUUID());
  }
  return (
    <Card title="Extract clauses from a contract text">
      <p className="mb-3 text-sm text-slate-600">
        Paste the text of the signed contract or load a .txt file (for a PDF, copy its text or run it through the OCR service first). The extractor splits it into clauses, matches them to the
        clause library, reads payment days, liability cap, notice period and governing law, and classifies each against the playbook. Nothing reaches the contract until you review it.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Source name">{(id) => <Input id={id} value={source} onChange={(e) => { setSource(e.target.value); setKey(crypto.randomUUID()); }} placeholder="e.g. SA-5520 signed copy.pdf" />}</Field>
        <Field label="Load a .txt file">{(id) => <input id={id} type="file" accept=".txt,text/plain" onChange={pick} className="text-sm" />}</Field>
      </div>
      <div className="mt-3">
        <Field label="Contract text" hint={`${text.length.toLocaleString('en-IN')} characters`}>
          {(id) => <Textarea id={id} rows={10} className="font-mono text-xs" value={text} onChange={(e) => { setText(e.target.value); setKey(crypto.randomUUID()); }} />}
        </Field>
        {fileError && <p role="alert" className="mt-1 text-xs text-red-700">{fileError}</p>}
      </div>
      <div className="mt-3"><ProblemBox error={create.error} /></div>
      <div className="mt-3 flex justify-end">
        <Button variant="primary" busy={create.isPending} disabled={text.trim().length < 20 || text.length > MAX_TEXT} onClick={() => create.mutate()}>Extract clauses</Button>
      </div>
    </Card>
  );
}

const confidenceTone = (c: number) => (c >= 0.85 ? 'bg-emerald-500' : c >= 0.7 ? 'bg-amber-500' : 'bg-red-500');

function ExtractionReview({ number, onBack }: { number: string; onBack: () => void }) {
  const { data: x, isLoading, error } = useApi<Extraction>(`/clause-extractions/${encodeURIComponent(number)}`);
  const [edits, setEdits] = useState<Record<number, Decision>>({});
  const [rejecting, setRejecting] = useState(false);
  const review = useCommand((decisions: { seq: number; action: string; text?: string; position?: string; code?: string }[]) =>
    api.post<Extraction>(`/clause-extractions/${encodeURIComponent(number)}/review`, { decisions }),
  { success: (r) => (r.status === 'REVIEWED' ? 'Review complete – ready to apply' : 'Review saved'), onSuccess: () => setEdits({}) });
  const apply = useCommand(() => api.post<{ contract: string; added: number; replaced: number }>(`/clause-extractions/${encodeURIComponent(number)}/apply`),
    { success: (r) => `${r.added} clause(s) added, ${r.replaced} replaced on ${r.contract}`, onSuccess: onBack });
  if (isLoading) return <Loading />;
  if (error || !x) return <ProblemBox error={error} />;

  const editable = x.status === 'EXTRACTED' || x.status === 'REVIEWED';
  const current = (i: Item): Decision | undefined => edits[i.seq] ?? (i.decision === 'ACCEPTED' ? { action: i.edited ? 'EDIT' : 'ACCEPT' } : i.decision === 'REJECTED' ? { action: 'REJECT' } : undefined);
  const set = (i: Item, patch: Partial<Decision>) => setEdits((e) => ({ ...e, [i.seq]: { action: 'ACCEPT', ...current(i), ...patch } }));
  const undecided = x.items.filter((i) => !current(i));
  const acceptedCodes = x.items.filter((i) => { const d = current(i); return d && d.action !== 'REJECT'; }).map((i) => (edits[i.seq]?.code ?? i.code));
  const duplicate = acceptedCodes.length !== new Set(acceptedCodes).size;
  const changed = Object.keys(edits).length > 0;
  const discrepancies = x.attributes.discrepancies ?? [];

  function save() {
    review.mutate(x!.items.flatMap((i) => {
      const d = current(i);
      if (!d) return [];
      return [{ seq: i.seq, action: d.action, ...(d.action === 'EDIT' ? { text: d.text ?? i.text, position: d.position ?? i.position, code: d.code ?? i.code } : {}) }];
    }));
  }
  function acceptConfident() {
    setEdits((e) => ({ ...e, ...Object.fromEntries(x!.items.filter((i) => !current(i) && i.confidence >= 0.85 && i.position !== 'NON_STANDARD').map((i) => [i.seq, { action: 'ACCEPT' as const }])) }));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={onBack}>← All extractions</Button>
          <h3 className="text-base font-semibold">{x.number}</h3>
          <StatusChip status={x.status === 'APPLIED' ? 'COMPLETED' : x.status === 'REVIEWED' ? 'READY' : x.status} />
          <span className="text-xs text-slate-500">{x.source_name} · {x.extractor_version} · {dateTime(x.created_at)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {editable && <Button variant="danger" onClick={() => setRejecting(true)}>Reject extraction</Button>}
          {x.status === 'EXTRACTED' && <Button onClick={acceptConfident}>Accept all ≥ 85% (not non-standard)</Button>}
          {x.status === 'EXTRACTED' && <Button variant="primary" busy={review.isPending} disabled={!changed || duplicate} onClick={save}>Save review</Button>}
          {x.status === 'REVIEWED' && <Button variant="primary" busy={apply.isPending} onClick={() => apply.mutate()}>Apply to {x.contract_ref}</Button>}
        </div>
      </div>
      <p className="text-sm text-slate-600">
        {x.summary.items} clause(s) found · {x.summary.pending} to review · {x.summary.lowConfidence} below 70% confidence · {x.summary.nonStandard} non-standard (these route the contract approval through Legal).
        {undecided.length > 0 && ` ${undecided.length} still undecided.`}
      </p>
      {duplicate && <p role="alert" className="text-sm text-red-700">Two accepted items share a clause code: reject one or change its code.</p>}
      <ProblemBox error={review.error ?? apply.error} />

      {x.attributes.parties?.length || x.attributes.validFrom || x.attributes.validTo ? (
        <p className="text-sm text-slate-700">
          Document facts:{x.attributes.parties?.length ? ` ${x.attributes.parties.join(' / ')};` : ''}
          {x.attributes.validFrom ? ` from ${date(x.attributes.validFrom)}` : ''}{x.attributes.validTo ? ` to ${date(x.attributes.validTo)}` : ''}{x.attributes.autoRenewal ? '; renews automatically' : ''}.
        </p>
      ) : null}
      {discrepancies.length > 0 && (
        <div role="status" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">The document differs from the contract record</p>
          <ul className="mt-1 list-disc pl-5">{discrepancies.map((d) => <li key={d.field}>{label(d.field)}: document says <span className="font-mono">{String(d.document)}</span>, record has <span className="font-mono">{String(d.contract)}</span></li>)}</ul>
          <p className="mt-1 text-xs">Applying clauses does not change the contract record; correct it with an amendment if the document is right.</p>
        </div>
      )}

      <ul className="space-y-3">
        {x.items.map((i) => {
          const d = current(i);
          const pct = Math.round(i.confidence * 100);
          return (
            <li key={i.seq} className={`rounded-lg border p-3 ${d?.action === 'REJECT' ? 'border-slate-200 bg-slate-50 opacity-70' : i.position === 'NON_STANDARD' ? 'border-red-200' : 'border-slate-200'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-slate-500">{edits[i.seq]?.code ?? i.code}</span>
                <span className="text-sm font-semibold">{i.title}</span>
                <PositionTag position={edits[i.seq]?.position ?? i.position} />
                <span className="text-xs text-slate-500">risk {i.risk}</span>
                <span className="ml-auto flex items-center gap-2 text-xs text-slate-600" title={i.alternatives.map((a) => `${a.code} ${Math.round(a.confidence * 100)}%`).join(', ') || 'no alternative match'}>
                  line {i.line} · confidence {pct}%
                  <span className="h-1.5 w-20 rounded-full bg-slate-100" aria-hidden><span className={`block h-1.5 rounded-full ${confidenceTone(i.confidence)}`} style={{ width: `${pct}%` }} /></span>
                </span>
              </div>
              {i.positionReason && <p className="mt-1 text-xs text-slate-600">{i.positionReason}</p>}
              {Object.keys(i.attributes).length > 0 && (
                <p className="mt-1 font-mono text-[11px] text-slate-500">{Object.entries(i.attributes).map(([k, v]) => `${k}=${String(v)}`).join(' · ')}</p>
              )}
              {d?.action === 'EDIT' ? (
                <div className="mt-2 grid gap-2 md:grid-cols-3">
                  <div className="md:col-span-3"><Field label="Clause text">{(id) => <Textarea id={id} value={d.text ?? i.text} onChange={(e) => set(i, { action: 'EDIT', text: e.target.value })} />}</Field></div>
                  <Field label="Position">{(id) => <Select id={id} value={d.position ?? i.position} onChange={(e) => set(i, { action: 'EDIT', position: e.target.value })} options={POSITIONS.map((p) => ({ value: p, label: label(p) }))} />}</Field>
                  <Field label="Clause code">{(id) => <Input id={id} value={d.code ?? i.code} onChange={(e) => set(i, { action: 'EDIT', code: e.target.value.toUpperCase() })} />}</Field>
                </div>
              ) : <p className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2 text-sm text-slate-700">{i.text}</p>}
              {editable && (
                <div className="mt-2 flex flex-wrap items-center gap-2" role="radiogroup" aria-label={`Decision for ${i.title}`}>
                  {(['ACCEPT', 'EDIT', 'REJECT'] as const).map((a) => (
                    <button key={a} type="button" role="radio" aria-checked={d?.action === a} onClick={() => set(i, { action: a })}
                      className={`rounded-lg border px-3 py-1 text-xs font-semibold ${d?.action === a ? 'border-[#1A56DB] bg-blue-50 text-[#1A56DB]' : 'border-slate-300 text-slate-700 hover:bg-slate-50'}`}>
                      {a === 'ACCEPT' ? 'Accept' : a === 'EDIT' ? 'Edit' : 'Reject'}
                    </button>
                  ))}
                  {!d && <span className="text-xs text-amber-700">undecided</span>}
                  {i.reviewedBy && <span className="text-xs text-slate-500">saved by {i.reviewedBy}{i.reviewNote ? ` – ${i.reviewNote}` : ''}</span>}
                </div>
              )}
              {!editable && <p className="mt-1 text-xs text-slate-500">{label(i.decision)}{i.reviewedBy ? ` by ${i.reviewedBy}` : ''}</p>}
            </li>
          );
        })}
      </ul>

      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Text that matched no clause ({x.unmatched.length})</h4>
        {!x.unmatched.length ? <Empty title="Every block of the text was matched" /> : (
          <ul className="space-y-2">
            {x.unmatched.map((u, n) => (
              <li key={n} className="rounded-lg border border-dashed border-slate-300 p-3 text-sm">
                <p className="text-xs text-slate-500">line {u.line}{u.heading ? ` · ${u.heading}` : ''}{u.suggestions.length ? ` · closest ${u.suggestions.join(', ')} (${Math.round(u.confidence * 100)}%)` : ''}{u.note ? ` · ${u.note}` : ''}</p>
                <p className="mt-1 whitespace-pre-wrap text-slate-700">{u.text.length > 600 ? `${u.text.slice(0, 600)}…` : u.text}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-slate-500">Unmatched text is not written to the contract. Add it by hand as a clause redline or amendment when it matters.</p>
      </div>
      {rejecting && <RejectDialog extraction={x} onClose={() => { setRejecting(false); }} onDone={onBack} />}
    </div>
  );
}

function PositionTag({ position }: { position: string }) {
  const tone = position === 'STANDARD' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : position === 'FALLBACK' ? 'bg-amber-50 text-amber-800 ring-amber-200' : 'bg-red-50 text-red-800 ring-red-200';
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ring-1 ring-inset ${tone}`}>{position.replace(/_/g, ' ')}</span>;
}

function RejectDialog({ extraction, onClose, onDone }: { extraction: Extraction; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState('');
  const reject = useCommand(() => api.post(`/clause-extractions/${encodeURIComponent(extraction.number)}/reject`, { reason: reason.trim() }),
    { success: `${extraction.number} rejected`, onSuccess: () => { onClose(); onDone(); } });
  return (
    <Dialog open title={`Reject ${extraction.number}`} onClose={onClose}>
      <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      <div className="mt-3"><ProblemBox error={reject.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Keep</Button>
        <Button variant="danger" busy={reject.isPending} disabled={!reason.trim()} onClick={() => reject.mutate()}>Reject extraction</Button>
      </div>
    </Dialog>
  );
}
