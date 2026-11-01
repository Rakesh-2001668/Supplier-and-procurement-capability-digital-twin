'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Question = { id: string; pillar: string; text: string; weight: number; certificates: string[] };
type Assessment = {
  id: string; kind: 'ESG' | 'CYBER'; as_of: string; expires_on: string | null; score: string; status: string; evidence: string[]; submitted_by: string;
  reviewed_by: string | null; review_note: string | null;
};
type AssessmentsView = { supplier: string; items: Assessment[]; questionnaires: Record<'ESG' | 'CYBER', Question[]> };
type Responsiveness = {
  period: string; rfqInvited: number; rfqResponded: number; rfqResponseRatePct: string | null; rfqResponseHours: string | null; capaResponseHours: string | null;
  esgScore: string | null;
};
type MeFull = { userId: string; roles: string[] };

const KINDS = { ESG: 'ESG (environment, social, governance)', CYBER: 'Cyber security' } as const;

/** Pending workflow 30: ESG and cyber questionnaires (portal input, buyer review) and the responsiveness and ESG scorecard measures. */
export function AssessmentsCard({ code, manager }: { code: string; manager: boolean }) {
  const path = `/suppliers/${encodeURIComponent(code)}`;
  const me = useApi<MeFull>('/me');
  const portal = !!me.data?.roles.includes('SUPPLIER_USER');
  const data = useApi<AssessmentsView>(`${path}/assessments`);
  const measures = useApi<Responsiveness[]>(me.data && !portal ? `${path}/responsiveness` : null);
  const [submitting, setSubmitting] = useState(false);
  const [reviewing, setReviewing] = useState<Assessment | null>(null);
  const refresh = useCommand(() => api.post(`${path}/scorecard-measures/refresh`), { success: 'RFQ response, CAPA response and ESG measures recomputed for this month' });

  return (
    <div className="space-y-5">
      <Card title="ESG and cyber-security assessments (SLM-08)" actions={(portal || manager) && <Button variant="primary" onClick={() => setSubmitting(true)}>Submit questionnaire</Button>}>
        {data.isLoading ? <Loading /> : data.error ? <ProblemBox error={data.error} /> : (
          <>
            <DataTable<Assessment> rows={data.data?.items ?? []} empty="No questionnaire submitted yet" columns={[
              { key: 'kind', header: 'Questionnaire', render: (a) => label(a.kind) },
              { key: 'as_of', header: 'As of', render: (a) => date(a.as_of) },
              { key: 'score', header: 'Score', align: 'right', render: (a) => `${Number(a.score).toFixed(1)} / 100` },
              { key: 'status', header: 'Status', render: (a) => <StatusChip status={a.status} /> },
              { key: 'expires_on', header: 'Valid until', render: (a) => {
                if (!a.expires_on) return '–';
                const expired = new Date(a.expires_on).getTime() < Date.now();
                return <span className={expired ? 'font-semibold text-red-700' : ''}>{date(a.expires_on)}{expired ? ' (expired)' : ''}</span>;
              } },
              { key: 'evidence', header: 'Certificates counted', render: (a) => (a.evidence.length ? a.evidence.join(', ') : '–') },
              { key: 'review_note', header: 'Review note', render: (a) => a.review_note ?? '–' },
              { key: 'actions', header: '', render: (a) => (manager && a.status === 'SUBMITTED' ? <Button onClick={() => setReviewing(a)}>Review</Button> : null) },
            ]} />
            <p className="mt-2 text-xs text-slate-500">The score is calculated from the answers; a Yes to a certified management system counts in full only while a valid certificate is on file.
              An accepted questionnaire is valid for the period set in rule SUPPLIER-ASSESSMENT and feeds ESG bid criteria, the scorecard and the cyber-risk signal. The person who submits cannot review.</p>
          </>
        )}
      </Card>

      {!portal && (
        <Card title="Responsiveness and ESG measures" actions={manager && <Button busy={refresh.isPending} onClick={() => refresh.mutate()}>Refresh this month</Button>}>
          {measures.isLoading || me.isLoading ? <Loading /> : measures.error ? <ProblemBox error={measures.error} /> : (
            <DataTable<Responsiveness & { id: string }> rows={[...(measures.data ?? [])].reverse().map((m) => ({ ...m, id: m.period }))} empty="No periods yet" columns={[
              { key: 'period', header: 'Period' },
              { key: 'rfqInvited', header: 'RFQs invited', align: 'right' },
              { key: 'rfqResponded', header: 'Responded', align: 'right' },
              { key: 'rfqResponseRatePct', header: 'Response rate', align: 'right', render: (m) => (m.rfqResponseRatePct ? `${m.rfqResponseRatePct}%` : '–') },
              { key: 'rfqResponseHours', header: 'Avg hours to first bid', align: 'right', render: (m) => m.rfqResponseHours ?? '–' },
              { key: 'capaResponseHours', header: 'Avg hours to CAPA response', align: 'right', render: (m) => m.capaResponseHours ?? '–' },
              { key: 'esgScore', header: 'ESG score', align: 'right', render: (m) => m.esgScore ?? '–' },
            ]} />
          )}
        </Card>
      )}
      {submitting && data.data && <SubmitDialog code={code} view={data.data} onClose={() => setSubmitting(false)} />}
      {reviewing && <ReviewDialog assessment={reviewing} onClose={() => setReviewing(null)} />}
    </div>
  );
}

function SubmitDialog({ code, view, onClose }: { code: string; view: AssessmentsView; onClose: () => void }) {
  const [kind, setKind] = useState<'ESG' | 'CYBER'>('ESG');
  const [asOf, setAsOf] = useState('');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const questions = view.questionnaires[kind];
  const complete = questions.every((q) => answers[`${kind}:${q.id}`]);
  const submit = useCommand(() => api.post(`/suppliers/${encodeURIComponent(code)}/assessments`, {
    kind, as_of: asOf || undefined, answers: Object.fromEntries(questions.map((q) => [q.id, answers[`${kind}:${q.id}`]])),
  }), { success: `${label(kind)} questionnaire submitted for review`, onSuccess: onClose });
  return (
    <Dialog open title={`Submit questionnaire – ${code}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Questionnaire">{(id) => <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as 'ESG' | 'CYBER')} options={Object.entries(KINDS).map(([value, text]) => ({ value, label: text }))} />}</Field>
        <Field label="As of (optional)" hint="Defaults to today">{(id) => <Input id={id} type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />}</Field>
      </div>
      <ol className="mt-4 space-y-3">
        {questions.map((q) => (
          <li key={q.id} className="rounded-lg border border-slate-200 p-3">
            <p className="text-sm text-slate-900"><span className="font-mono text-xs text-slate-500">{q.id}</span> {q.text}</p>
            <p className="text-xs text-slate-500">{q.pillar} · weight {q.weight}{q.certificates.length ? ` · counts in full only with a valid ${q.certificates.join(' / ')} certificate on file` : ''}</p>
            <div role="radiogroup" aria-label={q.text} className="mt-1.5 flex gap-4 text-sm">
              {['YES', 'PARTIAL', 'NO'].map((v) => (
                <label key={v} className="inline-flex items-center gap-1.5">
                  <input type="radio" className="accent-[#1A56DB]" name={`${kind}-${q.id}`} checked={answers[`${kind}:${q.id}`] === v}
                    onChange={() => setAnswers((a) => ({ ...a, [`${kind}:${q.id}`]: v }))} /> {label(v)}
                </label>
              ))}
            </div>
          </li>
        ))}
      </ol>
      <ProblemBox error={submit.error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!complete} busy={submit.isPending} onClick={() => submit.mutate()}>Submit</Button>
      </div>
    </Dialog>
  );
}

function ReviewDialog({ assessment, onClose }: { assessment: Assessment; onClose: () => void }) {
  const [note, setNote] = useState('');
  const review = useCommand((accept: boolean) => api.post(`/assessments/${assessment.id}/review`, { accept, note: note.trim() }), {
    success: `${label(assessment.kind)} assessment reviewed`, onSuccess: onClose });
  return (
    <Dialog open title={`Review ${label(assessment.kind)} questionnaire`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-700">As of {date(assessment.as_of)} · score {Number(assessment.score).toFixed(1)} / 100. Accepting makes it the supplier&apos;s current assessment; rejecting needs a reason. You cannot review a questionnaire you submitted yourself.</p>
      <Field label="Review note (required to reject)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={note.trim().length < 3} busy={review.isPending} onClick={() => review.mutate(false)}>Reject</Button>
        <Button variant="primary" busy={review.isPending} onClick={() => review.mutate(true)}>Accept</Button>
      </div>
    </Dialog>
  );
}
