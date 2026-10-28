'use client';

import Link from 'next/link';
import { Card, Kpi, Loading, PageHeader, ProblemBox, StatusChip } from '@/components/pic/ui';
import { useLive } from '@/components/pic/WorkspaceShell';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

type Dashboard = {
  asOf: string;
  spend: { totalMinor: number; contractCoveragePct: string | null; maverickPct: string | null };
  purchasing: { touchlessPct: string | null; released: number; byStatus: Record<string, number> };
  requisitions: { byStatus: Record<string, number>; avgApprovalHours: string | null };
  payables: { firstPassMatchPct: string | null; byStatus: Record<string, number>; openExceptions: number; paymentBlocked: number };
  savings: { negotiatedCr: string; avoidanceCr: string; realisedCr: string };
  suppliers: { total: number; categoryStatus: Record<string, number>; qualifiedCoveragePct: string | null };
  integration: { byStatus: Record<string, number>; postingSuccessPct: string | null };
  controls: { sodViolations: number; agentRuns: number };
  tasks: { open: number; overdue: number; mine: number };
  activity: { ts: string; objectType: string; objectRef: string; action: string; actor: string }[];
};

function StatusCounts({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <p className="text-sm text-slate-500">None yet</p>;
  return (
    <ul className="flex flex-wrap gap-2">
      {entries.map(([s, n]) => (
        <li key={s} className="flex items-center gap-1.5"><StatusChip status={s} /><span className="text-sm font-semibold tabular-nums">{n}</span></li>
      ))}
    </ul>
  );
}

export default function CommandCentre() {
  const { data, isLoading, error } = useApi<Dashboard>('/dashboard');
  const live = useLive();
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  const pct = (v: string | null) => (v === null ? '–' : `${v}%`);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="AIX-01 · Procurement command centre" title="Command centre"
        subtitle={<>Live from posted transactions · as of {dateTime(data.asOf)}. Realised savings count only posted invoices.</>} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Kpi label="My open tasks" value={data.tasks.mine} hint={<Link className="text-[#1A56DB] hover:underline" href="/pic/tasks">Open inbox →</Link>} tone={data.tasks.mine ? 'warn' : 'default'} />
        <Kpi label="Posted spend" value={inr(data.spend.totalMinor)} hint={`contracted ${pct(data.spend.contractCoveragePct)}`} />
        <Kpi label="Touchless PO" value={pct(data.purchasing.touchlessPct)} hint={`${data.purchasing.released} released`} tone="good" />
        <Kpi label="First-pass match" value={pct(data.payables.firstPassMatchPct)} hint={`${data.payables.openExceptions} open exceptions`} />
        <Kpi label="Negotiated savings" value={`₹${data.savings.negotiatedCr} Cr`} hint={`avoidance ₹${data.savings.avoidanceCr} Cr`} tone="good" />
        <Kpi label="Realised savings" value={`₹${data.savings.realisedCr} Cr`} hint="posted invoices only" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Purchase orders"><StatusCounts counts={data.purchasing.byStatus} /></Card>
        <Card title="Requisitions" actions={<span className="text-xs text-slate-500">avg approval {data.requisitions.avgApprovalHours ?? '–'} h</span>}>
          <StatusCounts counts={data.requisitions.byStatus} />
        </Card>
        <Card title="Invoices" actions={<span className="text-xs text-slate-500">{data.payables.paymentBlocked} on payment block</span>}>
          <StatusCounts counts={data.payables.byStatus} />
        </Card>
        <Card title="Suppliers by category status" actions={<span className="text-xs text-slate-500">qualified {pct(data.suppliers.qualifiedCoveragePct)}</span>}>
          <StatusCounts counts={data.suppliers.categoryStatus} />
        </Card>
        <Card title="ERP integration" actions={<span className="text-xs text-slate-500">posting success {pct(data.integration.postingSuccessPct)}</span>}>
          <StatusCounts counts={data.integration.byStatus} />
        </Card>
        <Card title="Controls">
          <dl className="grid grid-cols-3 gap-3 text-sm">
            <div><dt className="text-xs text-slate-500">Open tasks</dt><dd className="text-lg font-semibold">{data.tasks.open}</dd></div>
            <div><dt className="text-xs text-slate-500">Overdue</dt><dd className={`text-lg font-semibold ${data.tasks.overdue ? 'text-amber-700' : ''}`}>{data.tasks.overdue}</dd></div>
            <div><dt className="text-xs text-slate-500">SoD blocks</dt><dd className="text-lg font-semibold">{data.controls.sodViolations}</dd></div>
          </dl>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Live events" actions={<span className="text-xs text-slate-500">{live.connected ? 'streaming' : 'reconnecting…'}</span>}>
          {live.events.length === 0 ? <p className="text-sm text-slate-500">Events appear here as people and agents act (approvals, releases, receipts, postings).</p> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {live.events.map((e) => (
                <li key={e.id} className="flex flex-wrap justify-between gap-2 py-1.5">
                  <span><span className="font-mono text-xs text-[#1A56DB]">{e.type}</span> · {e.ref}</span>
                  <span className="text-xs text-slate-500">{e.actor} · {dateTime(e.at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Recent activity (audit)">
          <ul className="divide-y divide-slate-100 text-sm">
            {data.activity.map((a, i) => (
              <li key={i} className="flex flex-wrap justify-between gap-2 py-1.5">
                <span><span className="font-medium">{a.objectRef ?? a.objectType}</span> · {label(a.action)}</span>
                <span className="text-xs text-slate-500">{a.actor} · {dateTime(a.ts)}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
