'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { Button, Card, LinkButton, PageHeader, ProblemBox } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { TYPE_LABEL } from '@/lib/pic/links';

// The Copilot answer contract (AIX-02): every answer carries evidence, confidence, explanation and permission.
type Answer = {
  answer: string;
  evidence: { type: string; ref: string; link: string }[];
  confidence: { score: number; label: string; note: string };
  explanation: { method: string; modelVersion: string; dataFreshness: string };
  recommendedAction: { label: string; deepLink: string; requiresHuman: boolean } | null;
  permission: { role: string | null; autonomy: string; scopes: string[] };
};

type Turn = { id: number; question: string; askedAt: string; answer?: Answer; error?: ApiError | Error };

const SUGGESTED = [
  'Status of PO-77410', 'My approvals', 'Spend by supplier', 'Show savings', 'Open invoice exceptions',
  'Touchless and first-pass KPIs', 'Trichy Forge',
];

function ConfidenceBadge({ confidence }: { confidence: Answer['confidence'] }) {
  const level = confidence.label.toLowerCase();
  const pct = `${Math.round(Number(confidence.score) * 100)}%`;
  const tone = level === 'high' ? 'bg-emerald-50 text-emerald-800 ring-emerald-200'
    : level === 'medium' ? 'bg-amber-50 text-amber-800 ring-amber-200'
      : 'bg-red-50 text-red-800 ring-red-300';
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${tone}`}>
        {level === 'low' && <span aria-hidden>⚠</span>}
        {label(level)} confidence · {pct}
      </span>
      <span className="text-xs text-slate-600">{confidence.note}</span>
      {level === 'low' && (
        <p role="note" className="w-full rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-medium text-red-900">
          Low confidence: this answer only partly matches your question. Check the evidence before acting on it.
        </p>
      )}
    </div>
  );
}

function AnswerView({ a }: { a: Answer }) {
  return (
    <div className="space-y-3">
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-900">{a.answer}</p>
      <ConfidenceBadge confidence={a.confidence} />

      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Evidence ({a.evidence.length})</p>
        {a.evidence.length === 0 ? <p className="text-xs text-slate-500">No evidence records were returned for this answer.</p> : (
          <ul className="flex flex-wrap gap-1.5">
            {a.evidence.map((e, i) => (
              <li key={`${e.ref}-${i}`}>
                <Link href={e.link} className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-[#1A56DB] hover:bg-blue-100">
                  <span className="text-slate-500">{TYPE_LABEL[e.type] ?? label(e.type)}</span>
                  <span className="font-mono">{e.ref}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {a.recommendedAction ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Recommended</span>
          <LinkButton href={a.recommendedAction.deepLink} variant="primary">{a.recommendedAction.label} →</LinkButton>
          {a.recommendedAction.requiresHuman
            ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">Needs a human decision</span>
            : <span className="text-xs text-slate-500">Information only, no decision required</span>}
        </div>
      ) : <p className="text-xs text-slate-500">No action recommended.</p>}

      <details className="group rounded-lg border border-slate-200 text-sm">
        <summary className="cursor-pointer select-none px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">Explain this answer</summary>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 border-t border-slate-100 px-3 py-2 text-xs sm:grid-cols-2">
          <div><dt className="text-slate-500">Method</dt><dd className="font-medium text-slate-900">{a.explanation.method}</dd></div>
          <div><dt className="text-slate-500">Model version</dt><dd className="font-mono text-slate-900">{a.explanation.modelVersion}</dd></div>
          <div><dt className="text-slate-500">Data freshness</dt><dd className="font-medium text-slate-900">{dateTime(a.explanation.dataFreshness)}</dd></div>
          <div><dt className="text-slate-500">Answered as role</dt><dd className="font-medium text-slate-900">{label(a.permission.role)} · autonomy {a.permission.autonomy}</dd></div>
          <div className="sm:col-span-2"><dt className="text-slate-500">Permission scopes used</dt>
            <dd className="mt-0.5 flex flex-wrap gap-1">{a.permission.scopes.length ? a.permission.scopes.map((s) => (
              <span key={s} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">{s}</span>
            )) : <span className="text-slate-500">none</span>}</dd>
          </div>
        </dl>
      </details>
    </div>
  );
}

export default function Copilot() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [turns]);

  async function ask(text: string) {
    const q = text.trim();
    if (q.length < 2 || busy) return;
    const id = nextId.current++;
    setTurns((t) => [...t, { id, question: q, askedAt: new Date().toISOString() }]);
    setQuestion('');
    setBusy(true);
    try {
      const answer = await api.post<Answer>('/copilot/ask', { question: q });
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, answer } : x)));
    } catch (e) {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: e as ApiError } : x)));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  return (
    <div className="space-y-4">
      <PageHeader eyebrow="AIX-02 · Procurement Copilot" title="Copilot"
        subtitle="Ask about documents, approvals, spend, savings, invoices and suppliers. Every answer shows its evidence, confidence, method and the permission it ran under." />

      <div role="note" className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-medium text-blue-900">
        AI recommends. Humans decide. Numbers come from live queries.
      </div>

      <Card title="Conversation" actions={turns.length ? <Button variant="ghost" onClick={() => setTurns([])} disabled={busy}>Clear</Button> : undefined}>
        {turns.length === 0 ? (
          <p className="text-sm text-slate-500">Start with one of the suggested questions below, or type your own.</p>
        ) : (
          <ol className="space-y-5" aria-live="polite">
            {turns.map((t) => (
              <li key={t.id} className="space-y-2">
                <div className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[#1A56DB] px-3 py-2 text-sm text-white">
                    <span className="sr-only">You asked: </span>{t.question}
                  </div>
                </div>
                <div className="max-w-[92%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3">
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Copilot</p>
                  {t.answer ? <AnswerView a={t.answer} /> : t.error ? <ProblemBox error={t.error} /> : (
                    <p className="text-sm text-slate-500" aria-busy="true">Querying live data…</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
        <div ref={endRef} />
      </Card>

      <Card>
        <div className="mb-3">
          <p className="mb-1.5 text-xs font-medium text-slate-700">Suggested questions</p>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTED.map((s) => (
              <button key={s} type="button" disabled={busy} onClick={() => void ask(s)}
                className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:border-[#1A56DB] hover:text-[#1A56DB] disabled:cursor-not-allowed disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
        </div>
        <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex flex-1 flex-col gap-1">
            <label htmlFor="copilot-question" className="text-xs font-medium text-slate-700">Your question</label>
            <input id="copilot-question" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
              placeholder="e.g. Status of PO-77410"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-[#1A56DB] focus:outline-none focus:ring-2 focus:ring-[#1A56DB]/20" />
          </div>
          <Button type="submit" variant="primary" busy={busy} disabled={question.trim().length < 2}>Ask</Button>
        </form>
      </Card>
    </div>
  );
}
