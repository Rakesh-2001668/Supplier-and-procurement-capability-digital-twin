'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type Version = { id: string; code: string; version: string; kind: string; status: string; description: string | null; metrics: Record<string, unknown>;
  training: Record<string, unknown>; previousVersion: string | null; trainedAt: string | null; activatedAt: string | null; suspendedReason: string | null;
  builtIn: boolean };
type Code = { code: string; effectiveVersion: string; versions: Version[] };
type Drift = { code: string; version: string; monitor: string; feature: string | null; value: number; threshold: number; status: string; action: string; checkedAt: string };
type Evaluation = { code: string; version: string; dataset: string; metrics: Record<string, unknown>; gate: boolean | null; runAt: string };
type Registry = { models: Code[]; drift: Drift[]; evaluations: Evaluation[] };
type Gateway = { configured: boolean; enabled: boolean; mode: string; model: string; switchReason: string | null; monthSpentMicro: number; monthlyBudgetMicro: number;
  callsLastMinute: number; ratePerMinute: number; callsThisMonth: Record<string, number>; retentionDays: number;
  recentCalls: { at: string; purpose: string; status: string; reason: string | null; tokensIn: number; tokensOut: number; costMicro: number; latencyMs: number; redactions: Record<string, number> }[] };

const headline = (m: Record<string, unknown>) => {
  const flat: string[] = [];
  for (const [set, value] of Object.entries(m)) {
    if (value && typeof value === 'object') {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) if (typeof v === 'number' || typeof v === 'boolean') flat.push(`${k} ${v}`);
    }
    if (flat.length >= 4) break;
    void set;
  }
  return flat.slice(0, 4).join(' · ') || '–';
};

function ActionDialog({ version, action, onClose }: { version: Version; action: 'activate' | 'suspend'; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const cmd = useCommand(() => api.post(`/ai/models/${version.code}/${version.version}/${action}`, { reason: reason.trim() }), {
    success: action === 'activate' ? `${version.code}@${version.version} is active` : `${version.code}@${version.version} suspended; the previous version is active again`,
    onSuccess: onClose,
  });
  return (
    <Dialog open title={`${action === 'activate' ? 'Activate' : 'Suspend'} ${version.code}@${version.version}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">
          {action === 'activate' ? 'The platform uses this version from now on; the current one becomes retired and stays the fallback.'
            : 'The version is taken out of use and the previous version (or the built-in baseline) becomes active again.'}
        </p>
        <Field label="Reason (required, at least 5 characters)">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <ProblemBox error={cmd.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant={action === 'activate' ? 'primary' : 'danger'} disabled={reason.trim().length < 5} busy={cmd.isPending} onClick={() => cmd.mutate()}>
            {action === 'activate' ? 'Activate' : 'Suspend'}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function ModelsPanel({ canManage }: { canManage: boolean }) {
  const registry = useApi<Registry>('/ai/models');
  const gateway = useApi<Gateway>(canManage ? '/ai/gateway' : null);
  const [dialog, setDialog] = useState<{ version: Version; action: 'activate' | 'suspend' } | null>(null);
  const train = useCommand(() => api.post<Record<string, { trained?: boolean; reason?: string; activated?: boolean }>>('/ai/models/train', {}), {
    success: 'Training finished: see the registry below',
  });
  const drift = useCommand((code: string) => api.post<{ alerts: string[]; checked: boolean; reason?: string }>(`/ai/models/${code}/drift-check`, {}), {
    success: 'Drift check finished',
  });
  return (
    <div className="space-y-4">
      <Card title="Model registry and drift monitoring (TD §13)"
        actions={canManage ? <Button onClick={() => train.mutate()} busy={train.isPending}>Train from tenant data</Button> : undefined}>
        <p className="mb-3 text-sm text-slate-600">
          Every model that influences a business object is a versioned entry with its evaluation metrics. One version per model is active; the built-in baselines
          (rules, exponential smoothing, the seeded twin) are the fallback. A drift alert (population stability index above 0.25 or an accuracy drop above 0.10)
          suspends the active version and re-activates the previous one automatically. Trained results: {train.data ? Object.entries(train.data).map(([k, v]) =>
            `${label(k)} ${v.trained === false ? `not trained (${v.reason})` : v.activated ? 'activated' : 'candidate'}`).join('; ') : 'none in this session'}.
        </p>
        {registry.isLoading ? <Loading /> : registry.error ? <ProblemBox error={registry.error} /> : (
          <div className="space-y-4">
            {registry.data?.models.map((m) => (
              <div key={m.code} className="rounded-lg border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-slate-900">{label(m.code)} <span className="font-mono text-xs text-slate-500">{m.code}</span></p>
                  <div className="flex items-center gap-2 text-xs">Effective version <span className="font-mono">{m.effectiveVersion}</span>
                    {canManage && <Button onClick={() => drift.mutate(m.code)} busy={drift.isPending && drift.variables === m.code}>Check drift</Button>}</div>
                </div>
                <DataTable<Version> rows={m.versions} empty="Only the code-shipped version is in use; train to register one" columns={[
                  { key: 'version', header: 'Version', render: (v) => <span className="font-mono text-xs">{v.version}{v.builtIn ? ' (baseline)' : ''}</span> },
                  { key: 'status', header: 'Status', render: (v) => <StatusChip status={v.status} /> },
                  { key: 'kind', header: 'Kind', render: (v) => <span className="text-xs">{label(v.kind)}</span> },
                  { key: 'metrics', header: 'Metrics', className: 'min-w-[220px]', render: (v) => <span className="text-xs">{headline(v.metrics)}</span> },
                  { key: 'trainedAt', header: 'Trained', render: (v) => v.trainedAt ? <span className="whitespace-nowrap text-xs">{dateTime(v.trainedAt)}</span> : '–' },
                  { key: 'suspendedReason', header: 'Note', render: (v) => <span className="text-xs text-red-800">{v.suspendedReason ?? ''}</span> },
                  { key: 'action', header: '', render: (v) => canManage ? (
                    <div className="flex gap-2">
                      {v.status !== 'ACTIVE' && v.status !== 'SUSPENDED' && <Button onClick={() => setDialog({ version: v, action: 'activate' })}>Activate</Button>}
                      {v.status === 'ACTIVE' && !v.builtIn && <Button variant="danger" onClick={() => setDialog({ version: v, action: 'suspend' })}>Suspend</Button>}
                    </div>) : null },
                ]} />
              </div>
            ))}
            <ProblemBox error={drift.error ?? train.error} />
          </div>
        )}
      </Card>
      <Card title="Drift checks and evaluation runs">
        <DataTable<Drift & { id: string }> rows={(registry.data?.drift ?? []).map((d, i) => ({ ...d, id: `${i}` }))} empty="No drift check has run" columns={[
          { key: 'checkedAt', header: 'Checked', render: (d) => <span className="whitespace-nowrap text-xs">{dateTime(d.checkedAt)}</span> },
          { key: 'code', header: 'Model', render: (d) => <span className="font-mono text-xs">{d.code}@{d.version}</span> },
          { key: 'monitor', header: 'Monitor', render: (d) => `${d.monitor}${d.feature ? ` · ${d.feature}` : ''}` },
          { key: 'value', header: 'Value', align: 'right', render: (d) => `${d.value} / ${d.threshold}` },
          { key: 'status', header: 'Result', render: (d) => <StatusChip status={d.status} /> },
          { key: 'action', header: 'Action', render: (d) => d.action === 'FALLBACK' ? 'Fell back to the previous version' : '–' },
        ]} />
        <div className="mt-4">
          <DataTable<Evaluation & { id: string }> rows={(registry.data?.evaluations ?? []).map((e, i) => ({ ...e, id: `${i}` }))} empty="No evaluation has been recorded" columns={[
            { key: 'runAt', header: 'Run', render: (e) => <span className="whitespace-nowrap text-xs">{dateTime(e.runAt)}</span> },
            { key: 'code', header: 'Model', render: (e) => <span className="font-mono text-xs">{e.code}@{e.version}</span> },
            { key: 'dataset', header: 'Data set' },
            { key: 'metrics', header: 'Metrics', className: 'min-w-[240px]', render: (e) => <span className="text-xs">{headline({ m: e.metrics })}</span> },
            { key: 'gate', header: 'Gate', render: (e) => e.gate === null ? '–' : <StatusChip status={e.gate ? 'PASSED' : 'FAILED'} /> },
          ]} />
        </div>
      </Card>
      {canManage && (
        <Card title="LLM gateway">
          {gateway.isLoading ? <Loading /> : gateway.error ? <ProblemBox error={gateway.error} /> : gateway.data && (
            <>
              <p className="mb-2 text-sm text-slate-700">
                Mode <strong>{gateway.data.mode}</strong>{gateway.data.configured ? ` · model ${gateway.data.model}` : ' · PIC_LLM_GATEWAY_URL is not set, every answer is deterministic'}
                {gateway.data.switchReason ? ` · off: ${gateway.data.switchReason}` : ''}. {gateway.data.callsLastMinute}/{gateway.data.ratePerMinute} calls this minute; spend this month
                {' '}{gateway.data.monthSpentMicro / 1_000_000}{gateway.data.monthlyBudgetMicro ? ` of ${gateway.data.monthlyBudgetMicro / 1_000_000}` : ' (no budget set)'}.
                Prompts are redacted (GSTIN, PAN, bank accounts, e-mail, phone) before any call; only metadata is logged, for {gateway.data.retentionDays} days.
              </p>
              <DataTable<Gateway['recentCalls'][number] & { id: string }> rows={gateway.data.recentCalls.map((c, i) => ({ ...c, id: `${i}` }))} empty="No gateway call yet" columns={[
                { key: 'at', header: 'When', render: (c) => <span className="whitespace-nowrap text-xs">{dateTime(c.at)}</span> },
                { key: 'purpose', header: 'Purpose', render: (c) => label(c.purpose) },
                { key: 'status', header: 'Status', render: (c) => <StatusChip status={c.status} /> },
                { key: 'tokensIn', header: 'Tokens in/out', align: 'right', render: (c) => `${c.tokensIn}/${c.tokensOut}` },
                { key: 'latencyMs', header: 'ms', align: 'right' },
                { key: 'redactions', header: 'Redacted', render: (c) => Object.entries(c.redactions).map(([k, v]) => `${v} ${k}`).join(', ') || '–' },
                { key: 'reason', header: 'Note', render: (c) => <span className="text-xs">{c.reason ?? ''}</span> },
              ]} />
            </>
          )}
        </Card>
      )}
      {dialog && <ActionDialog version={dialog.version} action={dialog.action} onClose={() => setDialog(null)} />}
    </div>
  );
}
