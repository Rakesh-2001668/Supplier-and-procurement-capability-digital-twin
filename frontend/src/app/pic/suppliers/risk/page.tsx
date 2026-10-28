'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Kpi, LinkButton, Loading, PageHeader, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';

type Heat = { supplier: string; name: string; status: string; open: number; categories: string[]; worst: string };
type Signal = {
  id: string; supplier: string; category: string; severity: string; source: string; title: string; status: string; mitigation: string | null;
  detail: Record<string, unknown> | null; detectedAt: string;
};
type Monitor = { highRiskSupplierPct: string; suppliersWithSignals: number; heat: Heat[]; signals: Signal[] };

const RISK_CATEGORIES = ['COMPLIANCE', 'FRAUD', 'FINANCIAL', 'DELIVERY', 'QUALITY', 'CERTIFICATE'];
const SEVERITY_RANK: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };
const SEVERITY_TONE: Record<string, string> = {
  Critical: 'bg-red-600 text-white',
  High: 'bg-red-100 text-red-900',
  Medium: 'bg-amber-100 text-amber-900',
  Low: 'bg-slate-100 text-slate-700',
};
// Suggested first actions per risk category (the agent's recommendation carries the same guidance).
const SUGGESTED: Record<string, string> = {
  COMPLIANCE: 'Hold new awards, re-screen and escalate to compliance',
  CERTIFICATE: 'Request the renewed certificate; status turns Conditional on expiry',
  DELIVERY: 'Open a CAPA on delivery performance and increase expediting on open POs',
  QUALITY: 'Open a CAPA with 8D root-cause analysis; tighten incoming inspection',
  FINANCIAL: 'Review exposure (open POs and contracts) and qualify an alternate source',
  FRAUD: 'Hold payments until the bank change is re-verified by call-back',
};

function Severity({ value }: { value: string }) {
  return <span className={`inline-flex whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${SEVERITY_TONE[value] ?? SEVERITY_TONE.Low}`}>{value}</span>;
}

export default function SupplierRiskMonitor() {
  const { scopes, roles } = useMe();
  const { data, isLoading, error } = useApi<Monitor>('/supplier-risk');
  const [showClosed, setShowClosed] = useState(false);
  const [category, setCategory] = useState('');
  const [mitigating, setMitigating] = useState<Signal | null>(null);
  const scan = useCommand(() => api.post<{ newSignals: number }>('/supplier-risk/scan'), {
    success: (r) => (r.newSignals ? `Supplier Risk Agent raised ${r.newSignals} new signal(s) with mitigation recommendations` : 'Supplier Risk Agent found no new signals'),
  });
  const canScan = scopes.includes('supplier:manage');
  const canMitigate = !roles.length || roles.some((r) => ['SUPPLIER_MANAGER', 'CATEGORY_MANAGER', 'PROCUREMENT_HEAD'].includes(r));

  const signals = data?.signals ?? [];
  const open = signals.filter((s) => s.status !== 'CLOSED');
  const shown = signals.filter((s) => (showClosed || s.status !== 'CLOSED') && (!category || s.category === category));
  // Worst open severity per supplier and risk category.
  const cell = (supplier: string, cat: string) => open.filter((s) => s.supplier === supplier && s.category === cat)
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9));

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SLM-04 · Supplier risk monitor" title="Supplier risk"
        subtitle="Signals come from screening, certificates, scorecards, the supplier twin, financial-health tiers and the bank-change fraud rule. Each open signal has an owner and needs a mitigation."
        actions={<>
          <LinkButton href="/pic/suppliers">Suppliers</LinkButton>
          <LinkButton href="/pic/suppliers/performance">Performance</LinkButton>
          {canScan && <Button variant="primary" busy={scan.isPending} onClick={() => scan.mutate()}>Run Supplier Risk Agent</Button>}
        </>} />
      {scan.error && <ProblemBox error={scan.error} />}

      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data ? null : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="High-risk suppliers" value={`${data.highRiskSupplierPct}%`} hint="worst open signal High or Critical" tone={Number(data.highRiskSupplierPct) > 10 ? 'bad' : Number(data.highRiskSupplierPct) > 0 ? 'warn' : 'good'} />
            <Kpi label="Suppliers with signals" value={data.suppliersWithSignals} />
            <Kpi label="Open signals" value={open.length} tone={open.length ? 'warn' : 'good'} />
            <Kpi label="Critical open" value={open.filter((s) => s.severity === 'Critical').length} tone={open.some((s) => s.severity === 'Critical') ? 'bad' : 'good'} />
          </div>

          <Card title="Risk heat map" actions={<span className="text-xs text-slate-500">worst open severity per risk category</span>}>
            {!data.heat.length ? <Empty title="No supplier has an open risk signal" hint={canScan ? 'Run the Supplier Risk Agent to re-check the evidence.' : undefined} /> : (
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th scope="col" className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Supplier</th>
                      <th scope="col" className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Status</th>
                      {RISK_CATEGORIES.map((c) => <th key={c} scope="col" className="px-3 py-2 text-center text-xs font-semibold uppercase tracking-wide text-slate-500">{label(c)}</th>)}
                      <th scope="col" className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">Open</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {data.heat.map((h) => (
                      <tr key={h.supplier}>
                        <th scope="row" className="px-3 py-2 text-left font-normal">
                          <Link href={`/pic/suppliers/${encodeURIComponent(h.supplier)}`} className="font-medium text-[#1A56DB] hover:underline">{h.name}</Link>
                          <span className="block font-mono text-xs text-slate-500">{h.supplier}</span>
                        </th>
                        <td className="px-3 py-2"><StatusChip status={h.status} /></td>
                        {RISK_CATEGORIES.map((c) => {
                          const hits = cell(h.supplier, c);
                          return (
                            <td key={c} className="px-2 py-2 text-center">
                              {hits.length ? (
                                <button type="button" onClick={() => { setCategory(c); setShowClosed(false); }} title={hits.map((s) => s.title).join('\n')}
                                  className="rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB]" aria-label={`${hits[0].severity} ${label(c)} risk for ${h.supplier}: show signals`}>
                                  <Severity value={hits[0].severity} />{hits.length > 1 && <span className="ml-1 text-xs text-slate-500">×{hits.length}</span>}
                                </button>
                              ) : <span className="text-slate-300" aria-label="none">·</span>}
                            </td>
                          );
                        })}
                        <td className="px-3 py-2 text-right tabular-nums">{h.open}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Signals" actions={
            <div className="flex flex-wrap items-center gap-3">
              <Select aria-label="Filter signals by risk category" value={category} onChange={(e) => setCategory(e.target.value)}
                options={[{ value: '', label: 'All risk categories' }, ...RISK_CATEGORIES.map((c) => ({ value: c, label: label(c) }))]} />
              <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" className="accent-[#1A56DB]" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
                Include closed
              </label>
            </div>
          }>
            <DataTable<Signal> rows={shown} empty="No signals for this filter" columns={[
              { key: 'severity', header: 'Severity', render: (s) => <Severity value={s.severity} /> },
              { key: 'supplier', header: 'Supplier', render: (s) => <Link href={`/pic/suppliers/${encodeURIComponent(s.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{s.supplier}</Link> },
              { key: 'category', header: 'Risk', render: (s) => label(s.category) },
              { key: 'title', header: 'Signal', className: 'min-w-[220px]', render: (s) => <span>{s.title}<span className="block text-xs text-slate-500">{label(s.source)}</span></span> },
              { key: 'detectedAt', header: 'Detected', render: (s) => dateTime(s.detectedAt) },
              { key: 'status', header: 'Status', render: (s) => <StatusChip status={s.status} /> },
              { key: 'mitigation', header: 'Mitigation', className: 'min-w-[200px]', render: (s) => (s.mitigation ? <span className="text-xs text-slate-700">{s.mitigation}</span> : <span className="text-xs text-slate-400">none yet</span>) },
              { key: 'actions', header: '', render: (s) => (s.status !== 'CLOSED' && canMitigate ? <Button onClick={() => setMitigating(s)}>Mitigate</Button> : null) },
            ]} />
            {!canMitigate && <p className="mt-2 text-xs text-slate-500">Signals are mitigated by supplier management, category management or the procurement head.</p>}
          </Card>
        </>
      )}

      {mitigating && <MitigationDialog signal={mitigating} onClose={() => setMitigating(null)} />}
    </div>
  );
}

function MitigationDialog({ signal, onClose }: { signal: Signal; onClose: () => void }) {
  const [action, setAction] = useState(signal.mitigation ?? '');
  const [close, setClose] = useState(false);
  const save = useCommand(() => api.post<Signal>(`/risk-signals/${signal.id}/mitigation`, { action: action.trim(), close }), {
    success: `${signal.supplier}: ${close ? 'signal closed' : 'mitigation recorded'}`, onSuccess: onClose });
  return (
    <Dialog open title={`Mitigate – ${signal.supplier}`} onClose={onClose}>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-slate-700"><Severity value={signal.severity} /> {label(signal.category)} · {signal.title}</div>
      <Field label="Mitigation action (required)" hint={SUGGESTED[signal.category] ? `Suggested: ${SUGGESTED[signal.category]}` : undefined}>{(id) => (
        <Textarea id={id} value={action} onChange={(e) => setAction(e.target.value)} placeholder={SUGGESTED[signal.category] ?? 'Describe the action taken'} />
      )}</Field>
      {SUGGESTED[signal.category] && !action && (
        <Button variant="ghost" className="mt-2" onClick={() => setAction(SUGGESTED[signal.category])}>Use suggested action</Button>
      )}
      <fieldset className="mt-3">
        <legend className="text-xs font-medium text-slate-700">Outcome</legend>
        <div className="mt-1 flex flex-wrap gap-4 text-sm">
          <label className="inline-flex items-center gap-2"><input type="radio" name="outcome" className="accent-[#1A56DB]" checked={!close} onChange={() => setClose(false)} /> Mitigating – keep the signal open</label>
          <label className="inline-flex items-center gap-2"><input type="radio" name="outcome" className="accent-[#1A56DB]" checked={close} onChange={() => setClose(true)} /> Resolved – close the signal</label>
        </div>
      </fieldset>
      {save.error && <div className="mt-3"><ProblemBox error={save.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!action.trim()} busy={save.isPending} onClick={() => save.mutate()}>{close ? 'Close signal' : 'Record mitigation'}</Button>
      </div>
    </Dialog>
  );
}
