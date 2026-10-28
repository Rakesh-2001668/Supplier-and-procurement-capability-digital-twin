'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Card, DataTable, Empty, Kpi, Loading } from '@/components/pic/ui';
import { crore, inr } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { LevelChip, periodRange, ShareBar, SpendProblem } from './shared';

type Ranked = { supplier: string; name: string; riskTier: string | null; spendMinor: number; sharePct: string; categories: string[] };
type Concentration = { category: string; spendMinor: number; suppliers: number; hhi: number; level: string; topSupplier: string; topSharePct: string };
type Cluster = { suppliers: { code: string; name: string; spendMinor: number }[]; reason: string };
type SuppliersView = { periods: [string, string]; totalMinor: number; ranking: Ranked[]; concentration: Concentration[]; duplicateClusters: Cluster[] };

const supplierLink = (code: string) => `/pic/suppliers/${encodeURIComponent(code)}`;

/** SPD-03 supplier view: ranking, HHI concentration per category and duplicate-supplier clusters. */
export function SuppliersTab() {
  const { data, isLoading, error } = useApi<SuppliersView>('/spend/suppliers');
  const [all, setAll] = useState(false);
  if (isLoading) return <Loading />;
  if (error) return <SpendProblem error={error} />;
  if (!data?.ranking.length) return <Empty title="No addressable spend in the last 12 months" />;

  const ranked = data.ranking.map((r, i) => ({ ...r, rank: i + 1 }));
  const shown = all ? ranked : ranked.slice(0, 15);
  const maxShare = Math.max(...data.ranking.map((r) => Number(r.sharePct)), 1);
  const high = data.concentration.filter((c) => c.level === 'HIGH').length;
  const top5 = data.ranking.slice(0, 5).reduce((s, r) => s + Number(r.sharePct), 0);

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">Addressable spend, {periodRange(data.periods)}.</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Addressable spend" value={crore(data.totalMinor)} hint={inr(data.totalMinor)} />
        <Kpi label="Active suppliers" value={data.ranking.length} hint={`top 5 hold ${top5.toFixed(1)}%`} />
        <Kpi label="Highly concentrated" value={`${high} / ${data.concentration.length}`} hint="categories with HHI above 2,500" tone={high ? 'warn' : 'good'} />
        <Kpi label="Duplicate clusters" value={data.duplicateClusters.length} hint="same PAN or similar legal name" tone={data.duplicateClusters.length ? 'warn' : 'good'} />
      </div>

      <Card title="Supplier ranking" actions={data.ranking.length > 15 && (
        <Button variant="ghost" onClick={() => setAll((v) => !v)} aria-expanded={all}>{all ? 'Show top 15' : `Show all ${data.ranking.length}`}</Button>
      )}>
        <DataTable<Ranked & { rank: number }> rows={shown} columns={[
          { key: 'rank', header: '#', align: 'right' },
          { key: 'supplier', header: 'Supplier', render: (r) => (
            <Link href={supplierLink(r.supplier)} className="font-medium text-[#1A56DB] hover:underline">{r.name} <span className="font-mono text-xs text-slate-500">{r.supplier}</span></Link>
          ) },
          { key: 'spendMinor', header: 'Spend', align: 'right', render: (r) => inr(r.spendMinor) },
          { key: 'sharePct', header: 'Share', render: (r) => <ShareBar value={Number(r.sharePct)} max={maxShare} label={`${r.sharePct}%`} /> },
          { key: 'riskTier', header: 'Risk tier', render: (r) => (r.riskTier ? <LevelChip level={r.riskTier} /> : '–') },
          { key: 'categories', header: 'Categories', render: (r) => <span className="font-mono text-xs text-slate-600">{r.categories.join(', ') || '–'}</span> },
        ]} />
      </Card>

      <Card title="Concentration by category (HHI)" actions={<span className="text-xs text-slate-500">HHI = Σ share² · low ≤ 1,500 · moderate ≤ 2,500 · high above</span>}>
        <DataTable<Concentration> rows={data.concentration} columns={[
          { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs font-semibold">{r.category}</span> },
          { key: 'spendMinor', header: 'Spend', align: 'right', render: (r) => crore(r.spendMinor) },
          { key: 'suppliers', header: 'Suppliers', align: 'right' },
          { key: 'hhi', header: 'HHI', align: 'right', render: (r) => r.hhi.toLocaleString('en-IN') },
          { key: 'level', header: 'Level', render: (r) => <LevelChip level={r.level} /> },
          { key: 'topSupplier', header: 'Largest supplier', render: (r) => (
            <span><Link href={supplierLink(r.topSupplier)} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{r.topSupplier}</Link> <span className="text-xs text-slate-500">{r.topSharePct}%</span></span>
          ) },
        ]} />
      </Card>

      <Card title="Possible duplicate suppliers">
        {!data.duplicateClusters.length ? <Empty title="No duplicate clusters" hint="No two suppliers share a PAN or a near-identical legal name." /> : (
          <ul className="grid gap-3 md:grid-cols-2">
            {data.duplicateClusters.map((c, i) => {
              const sum = c.suppliers.reduce((s, x) => s + x.spendMinor, 0);
              return (
                <li key={i} className="rounded-lg border border-amber-200 bg-amber-50/40 p-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">Matched on {c.reason} · combined {crore(sum)}</p>
                  <ul className="mt-2 space-y-1 text-sm">
                    {c.suppliers.map((s) => (
                      <li key={s.code} className="flex justify-between gap-3">
                        <Link href={supplierLink(s.code)} className="font-medium text-[#1A56DB] hover:underline">{s.name} <span className="font-mono text-xs text-slate-500">{s.code}</span></Link>
                        <span className="tabular-nums text-slate-700">{inr(s.spendMinor)}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-slate-600">Confirm with master-data stewardship before merging; consolidating duplicates also corrects concentration and ranking.</p>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
