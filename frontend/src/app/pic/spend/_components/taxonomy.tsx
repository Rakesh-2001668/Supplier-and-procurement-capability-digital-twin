'use client';

import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Field, Input, Loading, ProblemBox, Select } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';
import { SpendProblem } from './shared';

export type TaxonomyNode = { code: string; name: string; parentCode: string | null; level: number; keywords: string[]; addressable: boolean; active: boolean; lines: number };
const LEVELS: Record<number, string> = { 1: 'Segment', 2: 'Family', 3: 'Category', 4: 'Commodity' };
const MAINTAINERS = ['CATEGORY_MANAGER', 'MDM_STEWARD', 'PROCUREMENT_HEAD', 'TENANT_ADMIN'];

const parseKeywords = (text: string) => [...new Set(text.split(',').map((w) => w.trim().toLowerCase()).filter(Boolean))];

/** The spend taxonomy: segment, family, category and commodity, with the keywords the classifier learns from. Maintained by category managers and data stewards. */
export function TaxonomyPanel() {
  const { roles } = useMe();
  const canEdit = roles.some((r) => MAINTAINERS.includes(r));
  const { data, isLoading, error } = useApi<TaxonomyNode[]>('/spend/taxonomy');
  const [filter, setFilter] = useState('');
  const [level, setLevel] = useState('');
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<TaxonomyNode | null>(null);
  const nodes = data ?? [];
  const q = filter.trim().toLowerCase();
  const rows = nodes.filter((n) => (!level || String(n.level) === level)
    && (!q || n.code.toLowerCase().includes(q) || n.name.toLowerCase().includes(q) || n.keywords.some((k) => k.includes(q))));

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        Levels: segment (1), family (2), category (3) and an optional commodity (4). A word belongs to one category only (a second owner is refused). A node with spend lines cannot be retired.
        {!canEdit && ' You can read the taxonomy; a category manager, data steward or procurement head maintains it.'}
      </p>
      <Card title={`Taxonomy (${rows.length} of ${nodes.length})`} actions={canEdit && <Button variant="primary" onClick={() => setAdding(true)}>Add category or commodity</Button>}>
        <div className="mb-3 grid gap-3 md:grid-cols-4">
          <Field label="Search code, name or keyword">{(id) => <Input id={id} value={filter} onChange={(e) => setFilter(e.target.value)} />}</Field>
          <Field label="Level">{(id) => <Select id={id} value={level} onChange={(e) => setLevel(e.target.value)}
            options={[{ value: '', label: 'All levels' }, ...Object.entries(LEVELS).map(([v, name]) => ({ value: v, label: `${v} · ${name}` }))]} />}</Field>
        </div>
        {isLoading ? <Loading /> : error ? <SpendProblem error={error} permission="spend:read or mdm:request" /> : (
          <DataTable<TaxonomyNode & { id: string }> caption="Spend taxonomy" rows={rows.map((n) => ({ ...n, id: n.code }))} empty="No node matches" columns={[
            { key: 'code', header: 'Code', render: (n) => <span style={{ paddingLeft: (n.level - 1) * 12 }} className="font-mono text-xs font-semibold">{n.code}</span> },
            { key: 'name', header: 'Name' },
            { key: 'level', header: 'Level', render: (n) => LEVELS[n.level] ?? n.level },
            { key: 'parentCode', header: 'Parent', render: (n) => <span className="font-mono text-xs">{n.parentCode ?? '–'}</span> },
            { key: 'keywords', header: 'Keywords', className: 'min-w-[200px]', render: (n) => (n.keywords.length ? <span className="text-xs text-slate-700">{n.keywords.join(', ')}</span> : <span className="text-slate-500">–</span>) },
            { key: 'lines', header: 'Spend lines', align: 'right', render: (n) => n.lines.toLocaleString('en-IN') },
            { key: 'addressable', header: 'Addressable', render: (n) => (n.addressable ? 'Yes' : 'No') },
            { key: 'active', header: 'Active', render: (n) => (n.active ? 'Yes' : <span className="font-medium text-red-700">Retired</span>) },
            { key: 'actions', header: '', render: (n) => (canEdit && n.level >= 3 ? <Button onClick={() => setEditing(n)} aria-label={`Edit ${n.code}`}>Edit</Button> : null) },
          ]} />
        )}
      </Card>
      {adding && <AddDialog nodes={nodes} onClose={() => setAdding(false)} />}
      {editing && <EditDialog node={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function AddDialog({ nodes, onClose }: { nodes: TaxonomyNode[]; onClose: () => void }) {
  const parents = nodes.filter((n) => n.active && (n.level === 2 || n.level === 3));
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [parent, setParent] = useState(parents[0]?.code ?? '');
  const [keywords, setKeywords] = useState('');
  const [addressable, setAddressable] = useState(true);
  const codeOk = /^[A-Z][A-Z0-9-]{1,38}$/.test(code);
  const create = useCommand(() => api.post<TaxonomyNode>('/spend/taxonomy', { code, name: name.trim(), parent_code: parent, keywords: parseKeywords(keywords), addressable }), {
    success: `${code} added`, onSuccess: onClose,
  });
  return (
    <Dialog open title="Add to the taxonomy" onClose={onClose}>
      <div className="grid gap-3">
        <Field label="Parent" required hint="A family adds a category; a category adds a commodity">{(id, d) => (
          <Select id={id} aria-describedby={d} value={parent} onChange={(e) => setParent(e.target.value)}
            options={parents.map((n) => ({ value: n.code, label: `${n.code} · ${n.name} (${LEVELS[n.level]})` }))} />
        )}</Field>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Code" required hint="Capital letters, digits and hyphens, e.g. MRO-GASES" error={code && !codeOk ? 'Start with a capital letter; 2-39 characters of A-Z, 0-9 or -' : undefined}>
            {(id, d) => <Input id={id} aria-describedby={d} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />}
          </Field>
          <Field label="Name" required>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        </div>
        <Field label="Keywords" hint="Comma-separated, 2-60 characters each; the classifier matches them in invoice text">{(id, d) => <Input id={id} aria-describedby={d} value={keywords} onChange={(e) => setKeywords(e.target.value)} />}</Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={addressable} onChange={(e) => setAddressable(e.target.checked)} /> Addressable spend</label>
      </div>
      {create.error && <div className="mt-3"><ProblemBox error={create.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!codeOk || name.trim().length < 2 || !parent} busy={create.isPending} onClick={() => create.mutate()}>Add</Button>
      </div>
    </Dialog>
  );
}

function EditDialog({ node, onClose }: { node: TaxonomyNode; onClose: () => void }) {
  const [name, setName] = useState(node.name);
  const [keywords, setKeywords] = useState(node.keywords.join(', '));
  const [addressable, setAddressable] = useState(node.addressable);
  const [active, setActive] = useState(node.active);
  const save = useCommand(() => api.patch<TaxonomyNode>(`/spend/taxonomy/${encodeURIComponent(node.code)}`, { name: name.trim(), keywords: parseKeywords(keywords), addressable, active }), {
    success: `${node.code} saved`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Edit ${node.code}`} onClose={onClose}>
      <div className="grid gap-3">
        <Field label="Name" required>{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Keywords" hint="Comma-separated; a word another category already owns is refused (KEYWORD_CONFLICT)">{(id, d) => <Input id={id} aria-describedby={d} value={keywords} onChange={(e) => setKeywords(e.target.value)} />}</Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={addressable} onChange={(e) => setAddressable(e.target.checked)} /> Addressable spend</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#1A56DB]" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active
          {node.lines > 0 && <span className="text-xs text-slate-500">({node.lines.toLocaleString('en-IN')} spend lines: it cannot be retired until they are reclassified)</span>}</label>
      </div>
      {save.error && <div className="mt-3"><ProblemBox error={save.error} /></div>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={name.trim().length < 2} busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Dialog>
  );
}
