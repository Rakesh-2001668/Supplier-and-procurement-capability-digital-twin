'use client';

// SoD exception path (item 46) in the admin screen: per-rule mode (BLOCK or MITIGATE) and the report of every exception request,
// its approver's decision, validity window, compensating control and uses.

import { Button, Card, DataTable, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useCommand } from '@/lib/pic/hooks';

export type Mitigation = { id: string; ref: string; ruleCode: string; action: string; refs: Record<string, string>; justification: string; status: string;
  compensatingControl: string; approverRoles: string[]; maxUses: number; useCount: number; decisionComment: string | null; validFrom: string | null;
  validUntil: string | null; createdAt: string };
export type MitigationReportData = { summary: { byStatus: Record<string, number>; activeGrants: number; expiringWithin24h: string[]; uses: number }; items: Mitigation[] };

export function RuleModeButton({ code, mode, risk, isAdmin }: { code: string; mode: string; risk: string; isAdmin: boolean }) {
  const set = useCommand((next: string) => api.put(`/admin/sod/${code}`, { mode: next, reason: `Changed from the SoD screen to ${next}` }), {
    success: `${code} updated`,
  });
  if (!isAdmin) return <StatusChip status={mode} />;
  if (risk === 'Critical') return <span className="flex items-center gap-1"><StatusChip status={mode} /><span className="text-[11px] text-slate-500">never mitigable</span></span>;
  const next = mode === 'MITIGATE' ? 'BLOCK' : 'MITIGATE';
  return (
    <span className="flex items-center gap-2">
      <StatusChip status={mode} />
      <Button busy={set.isPending} onClick={() => set.mutate(next)} aria-label={`Set ${code} to ${next}`}>{next === 'MITIGATE' ? 'Allow exceptions' : 'Block only'}</Button>
    </span>
  );
}

export function MitigationReport({ data, isAdmin }: { data: MitigationReportData; isAdmin: boolean }) {
  const revoke = useCommand((id: string) => api.post(`/admin/sod/mitigations/${id}/revoke`, { reason: 'Revoked from the SoD screen' }), { success: 'Exception revoked' });
  const s = data.summary;
  return (
    <Card title={`Exceptions to segregation of duties (${data.items.length})`}>
      <p className="mb-3 text-sm text-slate-600">
        A rule in <strong>Allow exceptions</strong> mode lets the person who hit the conflict ask for an exception. The configured approvers (rule SOD-MITIGATION) decide;
        an approved exception is time-boxed and use-limited, carries a compensating control and is audited on every use. Critical rules are never mitigable.
      </p>
      <ul className="mb-3 flex flex-wrap gap-4 text-sm">
        <li><span className="font-semibold">{s.activeGrants}</span> active grant(s)</li>
        <li><span className="font-semibold">{s.uses}</span> use(s)</li>
        <li><span className="font-semibold">{s.expiringWithin24h.length}</span> expiring within 24 h{s.expiringWithin24h.length ? `: ${s.expiringWithin24h.join(', ')}` : ''}</li>
        {Object.entries(s.byStatus).map(([k, v]) => <li key={k}>{label(k)}: {v}</li>)}
      </ul>
      <DataTable<Mitigation & Record<string, unknown>> rows={data.items as (Mitigation & Record<string, unknown>)[]} empty="No exception has been requested" columns={[
        { key: 'ref', header: 'Exception', render: (r) => <span className="font-mono text-xs font-semibold">{r.ref}</span> },
        { key: 'action', header: 'Action', render: (r) => <span className="font-mono text-xs">{r.action}</span> },
        { key: 'refs', header: 'Object', render: (r) => <span className="font-mono text-[11px]">{Object.values(r.refs ?? {}).join(' · ')}</span> },
        { key: 'justification', header: 'Reason', className: 'min-w-[200px]' },
        { key: 'compensatingControl', header: 'Compensating control', className: 'min-w-[200px]' },
        { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
        { key: 'validUntil', header: 'Valid until', render: (r) => (r.validUntil ? dateTime(r.validUntil) : '–') },
        { key: 'useCount', header: 'Uses', render: (r) => `${r.useCount} / ${r.maxUses}` },
        { key: 'approverRoles', header: 'Approvers', render: (r) => r.approverRoles.map(label).join(' → ') },
        ...(isAdmin ? [{ key: 'actions', header: '', render: (r: Mitigation) => (r.status === 'APPROVED' || r.status === 'PENDING'
          ? <Button variant="danger" busy={revoke.isPending} onClick={() => revoke.mutate(r.id)}>Revoke</Button> : null) }] : []),
      ]} />
    </Card>
  );
}
