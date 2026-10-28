'use client';

import { useState } from 'react';
import { CartesianGrid, LabelList, Legend, ReferenceArea, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts';
import { Button, Card, DataTable, Dialog, Empty, Field, Kpi, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';
import { SpendProblem } from './shared';

type Evidence = {
  hhi?: number; direct?: boolean; window?: [string, string]; factors?: Record<string, string>; riskTiers?: string[]; maxLateProb?: string | null;
  spendSharePct?: string; qualifiedSuppliers?: number;
};
type Plan = {
  id: string; number: string; category: string; fiscal_year: string; spend_minor: number; profit_impact: string; supply_risk: string; kraljic: string;
  evidence: Evidence; levers: string[]; waves: string[]; budget_minor: number | null; savings_target_minor: number | null; status: string;
  approved_at: string | null; created_at: string;
};

const QUADRANTS = [
  { key: 'STRATEGIC', name: 'Strategic', color: '#2a78d6' },
  { key: 'LEVERAGE', name: 'Leverage', color: '#eb6834' },
  { key: 'NON_CRITICAL', name: 'Non-critical', color: '#1baf7a' },
  { key: 'BOTTLENECK', name: 'Bottleneck', color: '#6250d6' },
];
// Thresholds used by the plan generator: profit impact ≥ 5, supply risk ≥ 4.
const IMPACT_SPLIT = 5;
const RISK_SPLIT = 4;

type Point = { x: number; y: number; z: number; category: string; kraljic: string; number: string; spend: number };

function PlanTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.category} · {label(p.kraljic)}</p>
      <p className="text-slate-700">Profit impact {p.y.toFixed(2)} · supply risk {p.x.toFixed(2)}</p>
      <p className="tabular-nums text-slate-700">{crore(p.spend)} spend · {p.number}</p>
    </div>
  );
}

/** SPD-07 category strategy: Kraljic positioning from spend and supply-risk evidence, levers, waves and plan approval. */
export function StrategyTab() {
  const { scopes } = useMe();
  const { data, isLoading, error } = useApi<Plan[]>('/category-plans');
  const [approving, setApproving] = useState<Plan | null>(null);
  const regenerate = useCommand(() => api.post<Plan[]>('/category-plans', {}), {
    success: (r) => `${r.length} draft plan(s) regenerated from the last 12 months of spend; approved plans are kept as they are`,
  });
  const canGenerate = scopes.includes('savings:manage');
  const plans = data ?? [];
  const points: Point[] = plans.map((p) => ({ x: Number(p.supply_risk), y: Number(p.profit_impact), z: Number(p.spend_minor), category: p.category, kraljic: p.kraljic, number: p.number, spend: p.spend_minor }));
  const budget = plans.reduce((s, p) => s + Number(p.budget_minor ?? 0), 0);
  const target = plans.reduce((s, p) => s + Number(p.savings_target_minor ?? 0), 0);
  const fiscalYears = [...new Set(plans.map((p) => p.fiscal_year))];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          Profit impact scales with the category’s share of spend; supply risk combines criticality, concentration (HHI), single sourcing, supplier risk tier and the twin’s late-delivery probability.
          Plans are approved by the procurement head or CPO, never by the plan owner.
        </p>
        {canGenerate && (
          <div className="flex flex-col items-end gap-1">
            <Button variant="primary" busy={regenerate.isPending} onClick={() => regenerate.mutate()}>Regenerate plans</Button>
            <p className="text-xs text-slate-500">Recomputes draft plans for the current fiscal year.</p>
          </div>
        )}
      </div>
      {regenerate.error && <ProblemBox error={regenerate.error} />}

      {isLoading ? <Loading /> : error ? <SpendProblem error={error} /> : !plans.length ? (
        <Empty title="No category plans yet" hint={canGenerate ? 'Use Regenerate plans to position every category from the last 12 months of spend.' : 'A category manager generates plans from the spend data.'} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Plans" value={plans.length} hint={fiscalYears.length ? `FY ${fiscalYears.join(', ')}` : undefined} />
            <Kpi label="Approved" value={`${plans.filter((p) => p.status === 'APPROVED').length} / ${plans.length}`} tone="good" />
            <Kpi label="Budget" value={crore(budget)} hint="projected 12-month spend" />
            <Kpi label="Savings target" value={crore(target)} hint={budget ? `${((target * 100) / budget).toFixed(1)}% of budget` : undefined} tone="good" />
          </div>

          <Card title="Kraljic matrix" actions={<span className="text-xs text-slate-500">bubble size = spend</span>}>
            <div style={{ height: 420 }} role="img" aria-label="Scatter of categories by supply risk (x) and profit impact (y), in four Kraljic quadrants; the plan table below lists the same values">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 16, right: 24, bottom: 28, left: 8 }}>
                  <CartesianGrid stroke="#e2e8f0" />
                  <ReferenceArea x1={RISK_SPLIT} x2={10} y1={IMPACT_SPLIT} y2={10} fill="#f8fafc" fillOpacity={1} stroke="none"
                    label={{ value: 'STRATEGIC', position: 'insideTopRight', fill: '#64748b', fontSize: 11, fontWeight: 600 }} />
                  <ReferenceArea x1={0} x2={RISK_SPLIT} y1={IMPACT_SPLIT} y2={10} fill="#ffffff" fillOpacity={1} stroke="none"
                    label={{ value: 'LEVERAGE', position: 'insideTopLeft', fill: '#64748b', fontSize: 11, fontWeight: 600 }} />
                  <ReferenceArea x1={RISK_SPLIT} x2={10} y1={0} y2={IMPACT_SPLIT} fill="#ffffff" fillOpacity={1} stroke="none"
                    label={{ value: 'BOTTLENECK', position: 'insideBottomRight', fill: '#64748b', fontSize: 11, fontWeight: 600 }} />
                  <ReferenceArea x1={0} x2={RISK_SPLIT} y1={0} y2={IMPACT_SPLIT} fill="#f8fafc" fillOpacity={1} stroke="none"
                    label={{ value: 'NON-CRITICAL', position: 'insideBottomLeft', fill: '#64748b', fontSize: 11, fontWeight: 600 }} />
                  <XAxis type="number" dataKey="x" name="Supply risk" domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} tick={{ fontSize: 11, fill: '#64748b' }}
                    label={{ value: 'Supply risk →', position: 'insideBottom', offset: -16, fill: '#334155', fontSize: 12 }} />
                  <YAxis type="number" dataKey="y" name="Profit impact" domain={[0, 10]} ticks={[0, 2, 4, 6, 8, 10]} tick={{ fontSize: 11, fill: '#64748b' }} width={48}
                    label={{ value: 'Profit impact →', angle: -90, position: 'insideLeft', fill: '#334155', fontSize: 12 }} />
                  <ZAxis type="number" dataKey="z" range={[60, 600]} />
                  <Tooltip cursor={{ strokeDasharray: '3 3' }} content={<PlanTooltip />} />
                  <Legend verticalAlign="top" height={28} wrapperStyle={{ fontSize: 12, color: '#334155' }} />
                  {QUADRANTS.map((q) => (
                    <Scatter key={q.key} name={q.name} data={points.filter((p) => p.kraljic === q.key)} fill={q.color} stroke="#ffffff" strokeWidth={2} fillOpacity={0.85}>
                      <LabelList dataKey="category" position="right" style={{ fontSize: 10, fill: '#334155' }} />
                    </Scatter>
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="Category plans">
            <DataTable<Plan> rows={plans} columns={[
              { key: 'number', header: 'Plan', render: (p) => <span><span className="font-mono text-xs font-semibold">{p.number}</span><br /><span className="text-xs text-slate-500">FY {p.fiscal_year}</span></span> },
              { key: 'category', header: 'Category', render: (p) => <span className="font-mono text-xs font-semibold">{p.category}</span> },
              { key: 'kraljic', header: 'Quadrant', render: (p) => (
                <span className="inline-flex items-center gap-1.5 text-sm">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: QUADRANTS.find((q) => q.key === p.kraljic)?.color }} aria-hidden />
                  {label(p.kraljic)}
                </span>
              ) },
              { key: 'profit_impact', header: 'Impact / risk', align: 'right', render: (p) => <span className="tabular-nums">{Number(p.profit_impact).toFixed(2)} / {Number(p.supply_risk).toFixed(2)}</span> },
              { key: 'spend_minor', header: 'Spend', align: 'right', render: (p) => <span>{crore(p.spend_minor)}{p.evidence?.spendSharePct && <><br /><span className="text-xs text-slate-500">{p.evidence.spendSharePct}% of total</span></>}</span> },
              { key: 'budget_minor', header: 'Budget', align: 'right', render: (p) => crore(p.budget_minor) },
              { key: 'savings_target_minor', header: 'Savings target', align: 'right', render: (p) => <span title={inr(p.savings_target_minor)}>{crore(p.savings_target_minor)}</span> },
              { key: 'levers', header: 'Levers', className: 'min-w-[200px]', render: (p) => <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-700">{p.levers.map((l) => <li key={l}>{l}</li>)}</ul> },
              { key: 'waves', header: 'Waves', className: 'min-w-[200px]', render: (p) => <ol className="space-y-0.5 text-xs text-slate-700">{p.waves.map((w) => <li key={w}>{w}</li>)}</ol> },
              { key: 'evidence', header: 'Risk evidence', render: (p) => (
                <details className="text-xs text-slate-600">
                  <summary className="cursor-pointer font-medium text-[#1A56DB]">HHI {p.evidence?.hhi?.toLocaleString('en-IN') ?? '–'}</summary>
                  <ul className="mt-1 space-y-0.5">
                    <li>{p.evidence?.direct ? 'Direct' : 'Indirect'} · {p.evidence?.qualifiedSuppliers ?? 0} qualified supplier(s)</li>
                    {p.evidence?.maxLateProb && <li>Twin late-delivery prob. {p.evidence.maxLateProb}</li>}
                    {Object.entries(p.evidence?.factors ?? {}).map(([k, v]) => <li key={k}>{label(k.replace(/([A-Z])/g, '_$1'))}: {v}</li>)}
                  </ul>
                </details>
              ) },
              { key: 'status', header: 'Status', render: (p) => <span><StatusChip status={p.status} />{p.approved_at && <span className="mt-0.5 block text-xs text-slate-500">{dateTime(p.approved_at)}</span>}</span> },
              { key: 'actions', header: '', render: (p) => (p.status === 'DRAFT' ? <Button variant="primary" onClick={() => setApproving(p)}>Approve</Button> : null) },
            ]} />
          </Card>
        </>
      )}
      {approving && <ApproveDialog plan={approving} onClose={() => setApproving(null)} />}
    </div>
  );
}

function ApproveDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const [comment, setComment] = useState('');
  const approve = useCommand(() => api.post<Plan>(`/category-plans/${encodeURIComponent(plan.number)}/approve`, { comment: comment.trim() || undefined }), {
    success: `${plan.number} (${plan.category}) approved`, onSuccess: onClose });
  return (
    <Dialog open title={`Approve category plan – ${plan.number}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">{plan.category} · {label(plan.kraljic)} · budget {crore(plan.budget_minor)} · savings target {crore(plan.savings_target_minor)}.
        Only the procurement head or CPO may approve, and not the plan owner.</p>
      <Field label="Comment (optional)">{(id) => <Textarea id={id} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Agreed in the category review; start wave 1 in Q1" />}</Field>
      {approve.error && <div className="mt-3"><ProblemBox error={approve.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={approve.isPending} onClick={() => approve.mutate()}>Approve plan</Button>
      </div>
    </Dialog>
  );
}
