'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/pic/api';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { Button, Dialog, Field, Input, ProblemBox, Select } from './ui';

// ---------------------------------------------------------------- saved views (per user, optionally shared with the tenant)
export type SavedView = { id: string; screen: string; name: string; filters: Record<string, unknown>; shared: boolean; isDefault: boolean;
  owner: string | null; mine: boolean; etag: string };

/**
 * Saved filters for a worklist or analysis screen. `filters` is the current filter state; picking a view calls `onApply` with the
 * stored filters. The user's default view is applied once, when the list first arrives.
 */
export function SavedViews({ screen, filters, onApply }: { screen: string; filters: Record<string, unknown>; onApply: (filters: Record<string, unknown>) => void }) {
  const { data } = useApi<SavedView[]>(`/saved-views?screen=${encodeURIComponent(screen)}`);
  const [chosen, setChosen] = useState('');
  const [saving, setSaving] = useState(false);
  const applied = useRef(false);
  const views = data ?? [];
  const current = views.find((v) => v.id === chosen);

  useEffect(() => {
    if (applied.current || !data) return;
    applied.current = true;
    const mine = data.find((v) => v.isDefault && v.mine);
    if (mine) onApply(mine.filters);
  }, [data, onApply]);

  const remove = useCommand(() => api.delete(`/saved-views/${current?.id}`), { success: 'View deleted', onSuccess: () => setChosen('') });
  const makeDefault = useCommand(() => api.patch(`/saved-views/${current?.id}`, { is_default: true }, { ifMatch: current?.etag }), { success: 'Default view set' });

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Saved views">
      <label htmlFor={`views-${screen}`} className="text-xs font-medium text-ink-2">Saved views</label>
      <div className="w-56">
        <Select id={`views-${screen}`} value={chosen} onChange={(e) => {
          setChosen(e.target.value);
          const view = views.find((v) => v.id === e.target.value);
          if (view) onApply(view.filters);
        }} options={[{ value: '', label: views.length ? 'Choose a view…' : 'No saved views yet' },
          ...views.map((v) => ({ value: v.id, label: `${v.name}${v.isDefault ? ' (default)' : ''}${v.shared && !v.mine ? ` · ${v.owner ?? 'shared'}` : ''}` }))]} />
      </div>
      <Button onClick={() => setSaving(true)}>Save current filters</Button>
      {current?.mine && (
        <>
          {!current.isDefault && <Button variant="ghost" busy={makeDefault.isPending} onClick={() => makeDefault.mutate()}>Make default</Button>}
          <Button variant="ghost" busy={remove.isPending} onClick={() => remove.mutate()} aria-label={`Delete view ${current.name}`}>Delete view</Button>
        </>
      )}
      {saving && <SaveViewDialog screen={screen} filters={filters} onClose={() => setSaving(false)} onSaved={(id) => { setChosen(id); setSaving(false); }} />}
    </div>
  );
}

function SaveViewDialog({ screen, filters, onClose, onSaved }: { screen: string; filters: Record<string, unknown>; onClose: () => void; onSaved: (id: string) => void }) {
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  const [asDefault, setAsDefault] = useState(false);
  const save = useCommand(() => api.post<{ id: string }>('/saved-views', { screen, name: name.trim(), filters, shared, is_default: asDefault }),
    { success: 'View saved', onSuccess: (r) => onSaved(r.id) });
  const shown = Object.entries(filters).filter(([, v]) => v !== '' && v !== null && v !== undefined && !(Array.isArray(v) && !v.length));
  return (
    <Dialog open title="Save current filters" onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) save.mutate(); }} className="space-y-3">
        <Field label="Name" required hint="Up to 80 characters, unique on this screen">{(id, d) => <Input id={id} aria-describedby={d} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus />}</Field>
        <p className="text-xs text-ink-2">
          {shown.length ? <>Saves: {shown.map(([k, v]) => `${k} = ${Array.isArray(v) ? v.join(', ') : String(v)}`).join('; ')}</> : 'No filter is set: the view will show everything.'}
        </p>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-brand" checked={shared} onChange={(e) => setShared(e.target.checked)} /> Share with everyone in my organisation</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-brand" checked={asDefault} onChange={(e) => setAsDefault(e.target.checked)} /> Open this view by default</label>
        {save.error && <ProblemBox error={save.error} />}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={!name.trim()} busy={save.isPending}>Save view</Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- bulk actions: a result per row
export type BulkRowResult = { taskId: string; objectRef?: string | null; name?: string | null; decision: string; ok: boolean; status?: string;
  error?: { code: string; detail: string } };
export type BulkResult = { results: BulkRowResult[]; succeeded: number; failed: number };

/** Outcome of a bulk call, row by row: what went through and what was refused (and why). */
export function BulkResults({ result, onClose }: { result: BulkResult; onClose: () => void }) {
  return (
    <Dialog open title={`Bulk decision: ${result.succeeded} done, ${result.failed} refused`} onClose={onClose}>
      <ul className="divide-y divide-line text-sm" aria-label="Result per task">
        {result.results.map((r) => (
          <li key={r.taskId} className="flex flex-wrap items-start justify-between gap-2 py-2">
            <span><span className="font-medium">{r.objectRef ?? r.taskId.slice(0, 8)}</span>{r.name ? <span className="text-ink-3"> · {r.name}</span> : null}</span>
            {r.ok
              ? <span className="text-emerald-700">✓ {r.decision.toLowerCase()}d</span>
              : <span className="max-w-md text-right text-red-700"><span className="font-mono text-xs">{r.error?.code}</span> {r.error?.detail}</span>}
          </li>
        ))}
      </ul>
      <div className="mt-4 flex justify-end"><Button variant="primary" onClick={onClose}>Close</Button></div>
    </Dialog>
  );
}
