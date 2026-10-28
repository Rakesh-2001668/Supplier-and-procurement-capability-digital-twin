'use client';

import Link from 'next/link';
import { Card, DataTable, Empty, Kpi, Loading } from '@/components/pic/ui';
import { crore, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { pct, periodRange, SpendProblem } from './shared';

type Mover = { category: string; last3Minor: number; prior3Minor: number; changePct: string | null };
type Opportunity = { category: string; kind: string; valueMinor: number; text: string; deepLink: string };
type Overview = {
  periods: [string, string]; totalMinor: number; addressableMinor: number; addressablePct: string; underManagementPct: string;
  contractedPct: string; maverickPct: string; classificationAccuracyPct: string | null; openReviews: number; openMaverickHits: number;
  topMovers: Mover[]; opportunities: Opportunity[];
};

const KIND_HINT: Record<string, string> = {
  CONTRACT_COVERAGE: 'Off-contract value',
  CONSOLIDATION: 'Category spend',
  PRICE_VARIANCE: 'Price variance',
};

function Change({ value }: { value: string | null }) {
  if (value === null) return <span className="text-slate-500">new</span>;
  const n = Number(value);
  const up = n > 0;
  return (
    <span className={`tabular-nums font-medium ${up ? 'text-amber-700' : n < 0 ? 'text-emerald-700' : 'text-slate-600'}`}>
      <span aria-hidden>{up ? '▲ ' : n < 0 ? '▼ ' : ''}</span>{up ? '+' : ''}{value}%
      <span className="sr-only">{up ? ' increase' : n < 0 ? ' decrease' : ''}</span>
    </span>
  );
}

/** SPD-01 spend overview: trailing-12-month KPIs, top movers and the opportunity list. */
export function OverviewTab() {
  const { data, isLoading, error } = useApi<Overview>('/spend/overview');
  if (isLoading) return <Loading />;
  if (error) return <SpendProblem error={error} />;
  if (!data || !Number(data.totalMinor)) return <Empty title="No spend in the last 12 months" hint="Spend appears when invoices are posted to the ERP." />;

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">Trailing 12 complete months, {periodRange(data.periods)}. Shares are of addressable spend (intercompany transfers are not addressable).</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="12-month spend" value={crore(data.totalMinor)} hint={inr(data.totalMinor)} />
        <Kpi label="Addressable" value={pct(data.addressablePct)} hint={crore(data.addressableMinor)} />
        <Kpi label="Under management" value={pct(data.underManagementPct)} hint="contracted, or qualified supplier in an approved category plan" tone="good" />
        <Kpi label="Contracted" value={pct(data.contractedPct)} hint="contract or catalogue price" tone="good" />
        <Kpi label="Maverick" value={pct(data.maverickPct)} hint="addressable spend with a maverick flag" tone={Number(data.maverickPct) > 5 ? 'warn' : 'default'} />
        <Kpi label="Classification accuracy" value={pct(data.classificationAccuracyPct)} hint="auto-classified or accepted by a steward" />
        <Kpi label="Open reviews" value={data.openReviews} tone={data.openReviews ? 'warn' : 'default'}
          hint={<Link href="/pic/spend?tab=classification" className="font-medium text-[#1A56DB] hover:underline">Review classifications →</Link>} />
        <Kpi label="Open maverick hits" value={data.openMaverickHits} tone={data.openMaverickHits ? 'warn' : 'default'}
          hint={<Link href="/pic/spend?tab=maverick" className="font-medium text-[#1A56DB] hover:underline">Dispose hits →</Link>} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Top movers" actions={<span className="text-xs text-slate-500">last 3 months vs the 3 before</span>}>
          <DataTable<Mover> rows={data.topMovers} empty="No movement" columns={[
            { key: 'category', header: 'Category', render: (r) => <span className="font-mono text-xs font-semibold">{r.category}</span> },
            { key: 'last3Minor', header: 'Last 3 months', align: 'right', render: (r) => crore(r.last3Minor) },
            { key: 'prior3Minor', header: 'Prior 3 months', align: 'right', render: (r) => crore(r.prior3Minor) },
            { key: 'changePct', header: 'Change', align: 'right', render: (r) => <Change value={r.changePct} /> },
          ]} />
        </Card>

        <Card title="Opportunities" actions={<span className="text-xs text-slate-500">largest value first</span>}>
          {!data.opportunities.length ? <Empty title="No opportunities found" hint="Coverage, consolidation and price-variance checks found nothing to act on." /> : (
            <ul className="divide-y divide-slate-100">
              {data.opportunities.map((o, i) => (
                <li key={`${o.category}-${o.kind}-${i}`} className="flex flex-wrap items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900"><span className="font-mono text-xs">{o.category}</span> · {label(o.kind)}</p>
                    <p className="mt-0.5 text-sm text-slate-600">{o.text}</p>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <span className="text-sm font-semibold tabular-nums text-slate-900">{crore(o.valueMinor)}</span>
                    <span className="text-[11px] text-slate-500">{KIND_HINT[o.kind] ?? 'Value'}</span>
                    <Link href={o.deepLink} className="text-xs font-medium text-[#1A56DB] hover:underline">Act on this →</Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
