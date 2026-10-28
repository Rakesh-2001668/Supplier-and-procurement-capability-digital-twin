'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ResponsiveContainer, Tooltip, Treemap, TreemapNode } from 'recharts';
import { Card, Empty, Loading } from '@/components/pic/ui';
import { crore, inr } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { periodRange, ShareBar, SpendProblem } from './shared';

type SupplierLeaf = { supplier: string; name: string; valueMinor: number; lines: number };
type CategoryNode = { code: string; name: string; valueMinor: number; suppliers: SupplierLeaf[] };
type FamilyNode = { code: string; name: string; valueMinor: number; children: CategoryNode[] };
type SegmentNode = { code: string; name: string; valueMinor: number; children: FamilyNode[] };
type TreemapData = { periods: [string, string]; segments: SegmentNode[] };

type Item = { code: string; name: string; valueMinor: number; lines?: number; leaf: boolean };
const LEVELS = ['Segments', 'Families', 'Categories', 'Suppliers'];
// One hue, light → dark by rank: larger cells are darker.
const SHADES = ['#1A56DB', '#2f66df', '#4677e3', '#5f89e7', '#7a9ceb', '#97b2f0', '#b4c8f5'];

function CellTooltip({ active, payload, total }: { active?: boolean; payload?: { payload: { name: string; code: string; valueMinor: number } }[]; total: number }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-semibold text-slate-900">{p.name} <span className="font-mono font-normal text-slate-500">{p.code}</span></p>
      <p className="tabular-nums text-slate-700">{inr(p.valueMinor)} · {total ? ((p.valueMinor / total) * 100).toFixed(1) : '0'}%</p>
    </div>
  );
}

/** SPD-02 category drill-down: segment → family → category → supplier. */
export function CategoriesTab() {
  const { data, isLoading, error } = useApi<TreemapData>('/spend/treemap');
  const [path, setPath] = useState<string[]>([]);

  if (isLoading) return <Loading />;
  if (error) return <SpendProblem error={error} />;
  if (!data?.segments.length) return <Empty title="No spend in the last 12 months" />;

  const segment = path[0] ? data.segments.find((s) => s.code === path[0]) : undefined;
  const family = segment && path[1] ? segment.children.find((f) => f.code === path[1]) : undefined;
  const category = family && path[2] ? family.children.find((c) => c.code === path[2]) : undefined;

  const items: Item[] = category
    ? category.suppliers.map((s) => ({ code: s.supplier, name: s.name, valueMinor: s.valueMinor, lines: s.lines, leaf: true }))
    : family ? family.children.map((c) => ({ code: c.code, name: c.name, valueMinor: c.valueMinor, leaf: false }))
      : segment ? segment.children.map((f) => ({ code: f.code, name: f.name, valueMinor: f.valueMinor, leaf: false }))
        : data.segments.map((s) => ({ code: s.code, name: s.name, valueMinor: s.valueMinor, leaf: false }));
  const depth = category ? 3 : family ? 2 : segment ? 1 : 0;
  const total = items.reduce((s, i) => s + i.valueMinor, 0);
  const grand = data.segments.reduce((s, i) => s + i.valueMinor, 0);
  const crumbs = [{ code: '', name: 'All spend' }, ...[segment, family, category].filter(Boolean).map((n) => ({ code: n!.code, name: n!.name }))];
  const drill = (code: string) => depth < 3 && setPath([...path.slice(0, depth), code]);
  const chartData = items.filter((i) => i.valueMinor > 0).map((i, idx) => ({ name: i.name, code: i.code, valueMinor: i.valueMinor, size: i.valueMinor, fill: SHADES[Math.min(idx, SHADES.length - 1)] }));

  const renderCell = (node: TreemapNode) => {
    const { x, y, width, height, name } = node;
    const fill = String(node.fill ?? SHADES[0]);
    const dark = SHADES.indexOf(fill) < 4;
    const code = String(node.code ?? '');
    return (
      <g onClick={() => drill(code)} style={{ cursor: depth < 3 ? 'pointer' : 'default' }}>
        <rect x={x} y={y} width={width} height={height} fill={fill} stroke="#ffffff" strokeWidth={2} rx={4} />
        {width > 70 && height > 34 && (
          <>
            <text x={x + 8} y={y + 18} fontSize={12} fontWeight={600} fill={dark ? '#ffffff' : '#0B1020'}>{name.length > width / 7 ? `${name.slice(0, Math.floor(width / 7) - 1)}…` : name}</text>
            <text x={x + 8} y={y + 33} fontSize={11} fill={dark ? '#e0e7ff' : '#334155'}>{crore(Number(node.valueMinor))}</text>
          </>
        )}
      </g>
    );
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">Trailing 12 months, {periodRange(data.periods)}. Select a cell or a row to drill down; the breadcrumb takes you back up.</p>
      <nav aria-label="Category drill-down" className="flex flex-wrap items-center gap-1 text-sm">
        {crumbs.map((c, i) => (
          <span key={c.code || 'root'} className="flex items-center gap-1">
            {i > 0 && <span className="text-slate-400" aria-hidden>/</span>}
            {i === crumbs.length - 1 ? <span className="font-semibold text-slate-900" aria-current="page">{c.name}</span> : (
              <button type="button" className="font-medium text-[#1A56DB] hover:underline" onClick={() => setPath(path.slice(0, i))}>{c.name}</button>
            )}
          </span>
        ))}
      </nav>

      <Card title={`${LEVELS[depth]} · ${crore(total)}`} actions={<span className="text-xs text-slate-500">{depth ? `${((total / (grand || 1)) * 100).toFixed(1)}% of all spend` : `${items.length} segments`}</span>}>
        {!chartData.length ? <Empty title="No spend at this level" /> : (
          <div style={{ height: 300 }} role="img" aria-label={`Treemap of ${LEVELS[depth].toLowerCase()} by spend; the table below lists the same values`}>
            <ResponsiveContainer width="100%" height="100%">
              <Treemap data={chartData} dataKey="size" nameKey="name" isAnimationActive={false} content={renderCell}>
                <Tooltip content={<CellTooltip total={total} />} />
              </Treemap>
            </ResponsiveContainer>
          </div>
        )}

        <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                {[LEVELS[depth].replace(/s$/, ''), 'Spend', 'Share', ...(depth === 3 ? ['Invoice lines'] : [])].map((h, i) => (
                  <th key={h} scope="col" className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500 ${i === 1 || i === 3 ? 'text-right' : 'text-left'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {items.map((i) => (
                <tr key={i.code} className={!i.leaf ? 'hover:bg-blue-50/50' : ''}>
                  <td className="px-3 py-2">
                    {i.leaf ? (
                      <Link href={`/pic/suppliers/${encodeURIComponent(i.code)}`} className="font-medium text-[#1A56DB] hover:underline">{i.name} <span className="font-mono text-xs text-slate-500">{i.code}</span></Link>
                    ) : (
                      <button type="button" onClick={() => drill(i.code)} className="text-left font-medium text-[#1A56DB] hover:underline">
                        {i.name} <span className="font-mono text-xs text-slate-500">{i.code}</span>
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{inr(i.valueMinor)}</td>
                  <td className="px-3 py-2"><ShareBar value={total ? (i.valueMinor / total) * 100 : 0} /></td>
                  {depth === 3 && <td className="px-3 py-2 text-right tabular-nums">{i.lines}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
