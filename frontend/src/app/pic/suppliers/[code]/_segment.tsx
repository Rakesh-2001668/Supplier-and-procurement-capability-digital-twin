'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Kpi, Loading, ProblemBox, Select, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type SegmentRow = {
  id: string; segment: string; method: 'AUTO' | 'MANUAL'; spend_share: string; risk_score: number; criticality: string;
  inputs: { windowMonths?: number; supplierSpendMinor?: number; totalSpendMinor?: number; criticalityReasons?: string[]; manual?: boolean; setBy?: string;
    riskFactors?: { code: string; points: number; evidence: string }[] } | null;
  reason: string | null; rule_set_version: string | null; effective_from: string; effective_to: string | null;
};
type SegmentView = { supplier: string; segment: string | null; current: SegmentRow | null; history: SegmentRow[] };
type RiskScore = { supplier: string; score: number; level: string; factors: { code: string; points: number; evidence: string; severity?: string }[] };

const SEGMENT_TONE: Record<string, string> = {
  STRATEGIC: 'bg-violet-50 text-violet-800 ring-violet-200', LEVERAGE: 'bg-blue-50 text-blue-800 ring-blue-200',
  BOTTLENECK: 'bg-amber-50 text-amber-800 ring-amber-200', ROUTINE: 'bg-slate-100 text-slate-700 ring-slate-200',
};
const MEANING: Record<string, string> = {
  STRATEGIC: 'high spend share and exposed (risk or criticality): partner, plan together',
  LEVERAGE: 'high spend share, low exposure: compete and negotiate',
  BOTTLENECK: 'low spend share but exposed: secure supply, qualify an alternate',
  ROUTINE: 'low spend share, low exposure: simplify and automate',
};
const LEVEL_TONE: Record<string, 'good' | 'warn' | 'bad' | 'default'> = { LOW: 'good', MEDIUM: 'warn', HIGH: 'bad', CRITICAL: 'bad' };

export function SegmentChip({ segment }: { segment: string | null | undefined }) {
  if (!segment) return <span className="text-slate-500">–</span>;
  return <span className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${SEGMENT_TONE[segment] ?? SEGMENT_TONE.ROUTINE}`}>{segment}</span>;
}

/** Pending workflow 28: the supplier's segment, what it was based on, its history, the risk score, and a manual override. */
export function SegmentCard({ code, manager }: { code: string; manager: boolean }) {
  const path = `/suppliers/${encodeURIComponent(code)}`;
  const seg = useApi<SegmentView>(`${path}/segment`);
  const risk = useApi<RiskScore>(`${path}/risk-score`);
  const [override, setOverride] = useState(false);
  const recompute = useCommand(() => api.post('/supplier-segments/recompute'), { success: 'Segments recomputed from spend share and risk' });

  const current = seg.data?.current ?? null;
  const inputs = current?.inputs ?? null;
  return (
    <Card title="Segment and risk score (SLM-06)" actions={manager && (
      <>
        <Button onClick={() => setOverride(true)}>{current?.method === 'MANUAL' ? 'Change or clear override' : 'Override segment'}</Button>
        <Button variant="ghost" busy={recompute.isPending} onClick={() => recompute.mutate()}>Recompute all suppliers</Button>
      </>
    )}>
      {seg.isLoading ? <Loading /> : seg.error ? <ProblemBox error={seg.error} /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Segment</p>
              <p className="mt-1.5"><SegmentChip segment={seg.data?.segment} /></p>
              <p className="mt-1 text-xs text-slate-500">{current ? (current.method === 'MANUAL' ? 'set manually' : 'from the segmentation rule') : 'not segmented yet'}</p>
            </div>
            <Kpi label="Spend share" value={current ? `${Number(current.spend_share).toFixed(2)}%` : '–'}
              hint={inputs?.windowMonths ? `last ${inputs.windowMonths} months` : undefined} />
            <Kpi label="Risk score" value={risk.data ? risk.data.score : '–'} hint={risk.data ? label(risk.data.level) : undefined}
              tone={risk.data ? LEVEL_TONE[risk.data.level] ?? 'default' : 'default'} />
            <Kpi label="Criticality" value={current ? label(current.criticality) : '–'} hint={inputs?.criticalityReasons?.[0]} tone={current?.criticality === 'HIGH' ? 'warn' : 'default'} />
          </div>
          {current ? (
            <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <p><span className="font-semibold">{label(current.segment)}</span>: {MEANING[current.segment]}.</p>
              <p className="mt-1 text-xs text-slate-600">{current.reason}</p>
              {inputs?.supplierSpendMinor !== undefined && inputs.totalSpendMinor !== undefined && (
                <p className="mt-1 text-xs text-slate-600">Spend {inr(inputs.supplierSpendMinor)} of {inr(inputs.totalSpendMinor)} · rule {current.rule_set_version ?? '–'} · since {dateTime(current.effective_from)}</p>
              )}
              {inputs?.criticalityReasons && inputs.criticalityReasons.length > 0 && <p className="mt-1 text-xs text-slate-600">Criticality: {inputs.criticalityReasons.join('; ')}</p>}
            </div>
          ) : <Empty title="No segment yet" hint={manager ? 'Recompute the segments to place every supplier.' : 'A supplier manager runs the segmentation.'} />}
          {risk.data && risk.data.factors.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">What makes up the risk score</p>
              <ul className="space-y-0.5 text-sm text-slate-700">
                {risk.data.factors.map((f, i) => <li key={i}><span className="font-mono text-xs text-slate-500">{f.code}</span> +{f.points} · {f.evidence}</li>)}
              </ul>
            </div>
          )}
          {risk.error && <ProblemBox error={risk.error} />}
          {(seg.data?.history.length ?? 0) > 0 && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Segment history</p>
              <DataTable<SegmentRow> rows={seg.data?.history ?? []} columns={[
                { key: 'segment', header: 'Segment', render: (r) => <SegmentChip segment={r.segment} /> },
                { key: 'method', header: 'How', render: (r) => (r.method === 'MANUAL' ? 'Manual' : 'Automatic') },
                { key: 'spend_share', header: 'Spend share', align: 'right', render: (r) => `${Number(r.spend_share).toFixed(2)}%` },
                { key: 'risk_score', header: 'Risk', align: 'right' },
                { key: 'criticality', header: 'Criticality', render: (r) => label(r.criticality) },
                { key: 'effective_from', header: 'From', render: (r) => dateTime(r.effective_from) },
                { key: 'effective_to', header: 'To', render: (r) => (r.effective_to ? dateTime(r.effective_to) : 'current') },
                { key: 'reason', header: 'Reason', className: 'min-w-[220px]', render: (r) => <span className="text-xs text-slate-600">{r.reason ?? '–'}</span> },
              ]} />
            </div>
          )}
        </div>
      )}
      {override && <OverrideDialog code={code} current={current} onClose={() => setOverride(false)} />}
    </Card>
  );
}

function OverrideDialog({ code, current, onClose }: { code: string; current: SegmentRow | null; onClose: () => void }) {
  const [segment, setSegment] = useState(current?.method === 'MANUAL' ? current.segment : 'STRATEGIC');
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.put(`/suppliers/${encodeURIComponent(code)}/segment`, { segment: segment === 'AUTO' ? null : segment, reason: reason.trim() }), {
    success: segment === 'AUTO' ? `${code} returns to the automatic segment` : `${code} set to ${label(segment)}`, onSuccess: onClose });
  return (
    <Dialog open title={`Segment – ${code}`} onClose={onClose}>
      <p className="mb-3 text-sm text-slate-600">A manual segment stays until you clear it; the automatic recompute skips the supplier. The change is stored in the segment history with your reason.</p>
      <div className="grid gap-3">
        <Field label="Segment">{(id) => (
          <Select id={id} value={segment} onChange={(e) => setSegment(e.target.value)} options={[
            { value: 'STRATEGIC', label: 'Strategic' }, { value: 'LEVERAGE', label: 'Leverage' }, { value: 'BOTTLENECK', label: 'Bottleneck' },
            { value: 'ROUTINE', label: 'Routine' }, ...(current?.method === 'MANUAL' ? [{ value: 'AUTO', label: 'Back to the automatic segment' }] : []),
          ]} />
        )}</Field>
        <Field label="Reason (required)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Single source for the cover line; strategic review 2026-27" />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={reason.trim().length < 3} busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Dialog>
  );
}
