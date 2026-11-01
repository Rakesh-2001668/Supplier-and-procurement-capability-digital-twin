'use client';

// Industry template packs: preview what applying a pack changes (rule sets added, re-versioned or returned to default, and what is
// left alone because the tenant customised it), then apply. Applying never edits a rule version; re-applying changes nothing.

import { useState } from 'react';
import { Button, Card, Dialog, Loading, ProblemBox, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

type IndustryTemplate = { code: string; name: string; purchaseTypes: string[]; demandSources: string[]; eventTemplates: string[]; contractTemplates: string[];
  receipt: string; match: string; controls: string[]; kpis: string[]; demoCase: string; ruleOverrides: string[]; applied: boolean };
type Change = { key: string; action: 'ADD' | 'CHANGE' | 'REVERT'; fromVersion: string | null; description: string; fields: { field: string; from: unknown; to: unknown }[] };
type Preview = { template: string; name: string; current: string; alreadyApplied: boolean; switchesTemplate: boolean; noop: boolean; willAdd: number; willChange: number;
  ruleSetChanges: Change[]; unchangedRuleSets: string[]; customisedLeftAlone: { key: string; version: string; reason: string }[];
  history: { template: string; previousTemplate: string | null; appliedBy: string | null; appliedAt: string; changes: { ruleSets?: unknown[] } }[] };
type Applied = { applied: boolean; noop: boolean; message?: string; ruleSetChanges: { key: string; action: string; version?: string }[] };

const show = (v: unknown) => (v === null || v === undefined ? '–' : typeof v === 'object' ? JSON.stringify(v) : String(v));

function PreviewDialog({ code, isAdmin, onClose }: { code: string; isAdmin: boolean; onClose: () => void }) {
  const { data, isLoading, error } = useApi<Preview>(`/admin/templates/${code}/preview`);
  const [result, setResult] = useState<Applied | null>(null);
  const apply = useCommand(() => api.post<Applied>(`/admin/templates/${code}/apply`), {
    success: (r) => (r.applied ? `Template applied: ${r.ruleSetChanges.length} rule set(s) changed` : 'Nothing to change: the template is already applied'),
    onSuccess: setResult,
  });
  return (
    <Dialog open title={`Apply template · ${data?.name ?? code}`} onClose={onClose}>
      <div className="space-y-3">
        {isLoading && <Loading />}
        <ProblemBox error={error} />
        {data && !result && (
          <>
            <p className="text-sm text-slate-700">
              {data.alreadyApplied ? 'This tenant already runs this template.' : `The tenant moves from ${label(data.current)} to ${data.name}.`}{' '}
              {data.noop ? 'Every rule set is in place: applying changes nothing.' : `${data.willAdd} rule set(s) are added and ${data.willChange} become a new effective-dated version. Existing versions are kept, and documents in flight keep the version they started under.`}
            </p>
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {data.ruleSetChanges.map((c) => (
                <details key={c.key} className="rounded-lg border border-slate-200 px-3 py-2">
                  <summary className="cursor-pointer text-sm"><span className="font-mono text-xs font-semibold">{c.key}</span> <StatusChip status={c.action === 'ADD' ? 'NEW' : c.action === 'CHANGE' ? 'CHANGED' : 'REVERTED'} />
                    <span className="ml-2 text-xs text-slate-500">{c.description}</span></summary>
                  <table className="mt-2 w-full text-xs"><tbody>
                    {c.fields.map((f) => <tr key={f.field}><td className="pr-2 align-top font-mono">{f.field}</td><td className="pr-2 align-top text-slate-500">{show(f.from)}</td><td className="align-top">→ {show(f.to)}</td></tr>)}
                  </tbody></table>
                </details>
              ))}
              {data.customisedLeftAlone.map((c) => <p key={c.key} className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-900"><span className="font-mono">{c.key}@{c.version}</span>: {c.reason}</p>)}
            </div>
            {data.history.length > 0 && <p className="text-xs text-slate-500">Last applied: {label(data.history[0].template)} on {dateTime(data.history[0].appliedAt)}.</p>}
          </>
        )}
        {result && (
          <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
            {result.applied ? `Applied. ${result.ruleSetChanges.map((c) => `${c.key} ${c.action.toLowerCase()}${c.version ? ` @${c.version}` : ''}`).join(', ') || 'No rule changes.'}` : result.message}
          </p>
        )}
        <ProblemBox error={apply.error} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{result ? 'Close' : 'Cancel'}</Button>
          {isAdmin && !result && <Button variant="primary" disabled={!data || data.noop} busy={apply.isPending} onClick={() => apply.mutate()}>Apply template</Button>}
        </div>
      </div>
    </Dialog>
  );
}

export function TemplatesTab({ isAdmin }: { isAdmin: boolean }) {
  const { data, isLoading, error } = useApi<{ current: string; templates: IndustryTemplate[]; ruleSets: Record<string, string> }>('/admin/templates');
  const [preview, setPreview] = useState<string | null>(null);
  if (isLoading) return <Loading />;
  if (error || !data) return <ProblemBox error={error} />;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">Industry packs preconfigure purchase types, sourcing and contract templates, receipt and match rules, controls and KPIs.
        This tenant runs <span className="font-semibold">{data.templates.find((t) => t.applied)?.name ?? label(data.current)}</span>. Preview shows exactly which rule sets
        a pack would add or re-version before anything changes.{!isAdmin && ' Applying a pack needs the tenant administrator role.'}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        {data.templates.map((t) => (
          <Card key={t.code} className={t.applied ? 'ring-2 ring-[#1A56DB]' : ''}
            title={<span>{t.name} <span className="font-mono text-[11px] text-slate-500">{t.code}</span></span>}
            actions={<div className="flex items-center gap-2">{t.applied && <StatusChip status="ACTIVE" />}<Button onClick={() => setPreview(t.code)}>{isAdmin && !t.applied ? 'Preview and apply' : 'Preview'}</Button></div>}>
            <dl className="space-y-2 text-sm">
              {([['Purchase types', t.purchaseTypes.map((x) => label(x)).join(', ')], ['Demand', t.demandSources.join('; ')],
                ['Sourcing', t.eventTemplates.join('; ')], ['Contracts', t.contractTemplates.map((x) => label(x)).join(', ')], ['Receipt', t.receipt],
                ['Match', t.match], ['Controls', t.controls.join('; ')], ['KPIs', t.kpis.join(', ')], ['Demo case', t.demoCase],
                ['Rule overrides', t.ruleOverrides.length ? t.ruleOverrides.map((k) => `${k}${data.ruleSets[k] ? ` @${data.ruleSets[k]}` : ''}`).join(', ') : 'none']] as [string, string][])
                .map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[110px_1fr] gap-2">
                    <dt className="text-xs text-slate-500">{k}</dt><dd className="text-slate-800">{v || '–'}</dd>
                  </div>
                ))}
            </dl>
          </Card>
        ))}
      </div>
      {preview && <PreviewDialog code={preview} isAdmin={isAdmin} onClose={() => setPreview(null)} />}
    </div>
  );
}
