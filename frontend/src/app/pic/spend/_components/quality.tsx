'use client';

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Button, Card, DataTable, Empty, Kpi, Loading, ProblemBox } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { ChartBox, CubeState, CubeStatus, SpendProblem } from './shared';

type Check = {
  code: string; name: string; status: 'PASS' | 'WARN' | 'FAIL'; count: number; valueMinor: number; affectedPct: number; failAtPct: number; weight: number; penalty: number;
  detail: string; remedy: string; samples: unknown[];
};
type Report = {
  score: number; grade: string; lines: number; spendMinor: number; currency: string; checks: Check[]; runAt: string; failing: string[]; scope: Record<string, unknown> | null; runId?: string;
};
type Run = { id: string; runAt: string; score: number; lines: number; spendMinor: number; failing: string[] };

const TONE = {
  PASS: 'bg-emerald-50 text-emerald-800 ring-emerald-200', WARN: 'bg-amber-50 text-amber-800 ring-amber-200', FAIL: 'bg-red-50 text-red-800 ring-red-200',
} as const;
const ICON = { PASS: '✓', WARN: '!', FAIL: '✕' } as const;

function ScoreTooltip({ active, payload }: { active?: boolean; payload?: { payload: { at: string; score: number; failing: number } }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.at}</p>
      <p className="text-slate-700">Score {p.score}</p>
      <p className="text-slate-500">{p.failing} failing check{p.failing === 1 ? '' : 's'}</p>
    </div>
  );
}

/** Data quality of the cube: 14 checks, a 0-100 score, its stored history and a run action. */
export function QualityTab() {
  const report = useApi<Report>('/spend/quality');
  const history = useApi<{ runs: Run[] }>('/spend/quality/history?limit=30');
  const status = useApi<{ cube: CubeState }>('/spend/cube-status');
  const run = useCommand(() => api.post<Report>('/spend/quality/run', {}), {
    success: (r) => (r.runId ? `Quality run stored: score ${r.score}` : `Assessed, score ${r.score}. A user with a restricted spend scope gets the report but nothing is stored`),
  });
  const r = report.data;
  const runs = history.data?.runs ?? [];
  const chart = [...runs].reverse().map((x) => ({ at: dateTime(x.runAt), score: x.score, failing: x.failing.length }));
  const scoreTone = !r ? 'default' : r.score >= 90 ? 'good' : r.score >= 75 ? 'warn' : 'bad';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          The cube is only as good as the lines that feed it. Each check counts lines and value, names what to do about it, and costs the score a penalty (100 minus the penalties).
          The report is computed now; “Run and store” keeps it in the history. The scheduled job stores one every day.
        </p>
        <Button variant="primary" busy={run.isPending} onClick={() => run.mutate()}>Run and store assessment</Button>
      </div>
      {run.error && <ProblemBox error={run.error} />}
      <CubeStatus state={status.data?.cube} scope={r?.scope} />

      {report.isLoading ? <Loading text="Running the 14 checks…" /> : report.error ? <SpendProblem error={report.error} /> : !r ? null : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Quality score" value={`${r.score}`} hint={`grade ${r.grade} · out of 100`} tone={scoreTone} />
            <Kpi label="Failing checks" value={r.failing.length} hint={r.failing.length ? r.failing.map((c) => label(c)).join(', ') : 'none'} tone={r.failing.length ? 'bad' : 'good'} />
            <Kpi label="Lines assessed" value={r.lines.toLocaleString('en-IN')} />
            <Kpi label="Spend assessed" value={crore(r.spendMinor)} hint={`${r.currency} · ${dateTime(r.runAt)}`} />
          </div>

          <Card title="Checks">
            <ul className="divide-y divide-slate-100" aria-label="Data-quality checks">
              {r.checks.map((c) => (
                <li key={c.code} className="py-3 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900">
                        <span className={`mr-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${TONE[c.status]}`}>
                          <span aria-hidden>{ICON[c.status]}</span>{c.status}
                        </span>
                        {c.name} <span className="font-mono text-[11px] text-slate-500">{c.code}</span>
                      </p>
                      <p className="mt-1 text-sm text-slate-600">{c.detail}</p>
                      {c.status !== 'PASS' && <p className="mt-1 text-sm text-slate-800"><span className="font-medium">What to do: </span>{c.remedy}</p>}
                    </div>
                    <dl className="grid grid-cols-3 gap-x-4 text-right text-xs text-slate-600">
                      <div><dt>Lines</dt><dd className="font-semibold tabular-nums text-slate-900">{c.count.toLocaleString('en-IN')}</dd></div>
                      <div><dt>Affected</dt><dd className="font-semibold tabular-nums text-slate-900">{c.affectedPct}%</dd></div>
                      <div><dt>Penalty</dt><dd className="font-semibold tabular-nums text-slate-900">{c.penalty} / {c.weight}</dd></div>
                    </dl>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}

      <Card title="Score history" actions={<span className="text-xs text-slate-500">{runs.length} stored run{runs.length === 1 ? '' : 's'}</span>}>
        {history.isLoading ? <Loading /> : history.error ? <SpendProblem error={history.error} /> : !runs.length ? (
          <Empty title="No stored assessments yet" hint="Run and store an assessment to start the history." />
        ) : (
          <div className="space-y-4">
            {runs.length > 1 && (
              <ChartBox height={200} label="Line chart of the stored quality scores over time; the table below lists the same values">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chart} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                    <CartesianGrid vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="at" hide />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={32} />
                    <Tooltip content={<ScoreTooltip />} />
                    <Line dataKey="score" stroke="#1A56DB" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </ChartBox>
            )}
            <DataTable<Run> caption="Stored quality runs" rows={runs} columns={[
              { key: 'runAt', header: 'Run at', render: (x) => dateTime(x.runAt) },
              { key: 'score', header: 'Score', align: 'right', render: (x) => <span className="font-semibold">{x.score}</span> },
              { key: 'lines', header: 'Lines', align: 'right', render: (x) => x.lines.toLocaleString('en-IN') },
              { key: 'spendMinor', header: 'Spend', align: 'right', render: (x) => crore(x.spendMinor) },
              { key: 'failing', header: 'Failing checks', render: (x) => (x.failing.length ? x.failing.map((c) => label(c)).join(', ') : <span className="text-emerald-700">none</span>) },
            ]} />
          </div>
        )}
      </Card>
    </div>
  );
}
