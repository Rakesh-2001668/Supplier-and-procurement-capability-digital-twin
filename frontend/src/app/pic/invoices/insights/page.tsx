'use client';

import Link from 'next/link';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Card, DataTable, Empty, Kpi, LinkButton, Loading, PageHeader, ProblemBox } from '@/components/pic/ui';
import { inr } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

type Accrual = { po: string; line: number; supplier: string; accrualMinor: number; ageDays: number; bucket: '0-30' | '31-90' | '90+' };
type Insights = {
  dueLadderMinor: Record<'overdue' | '0-7' | '8-30' | '31-60' | '60+', number>;
  dpoDays: string | null; discountAvailableMinor: number; discountCapturedMinor: number; discountCapturePct: string | null; discountNote: string | null;
  firstPassMatchPct: string | null; duplicatesPrevented: number; grirAgeingMinor: Record<'0-30' | '31-90' | '90+', number>; grir: Accrual[];
};

const LADDER: { key: keyof Insights['dueLadderMinor']; name: string; fill: string }[] = [
  { key: 'overdue', name: 'Overdue', fill: '#dc2626' },
  { key: '0-7', name: 'Due 0–7 d', fill: '#d97706' },
  { key: '8-30', name: '8–30 d', fill: '#1A56DB' },
  { key: '31-60', name: '31–60 d', fill: '#3b82f6' },
  { key: '60+', name: '60+ d', fill: '#93c5fd' },
];
const AGEING: { key: keyof Insights['grirAgeingMinor']; name: string; tone: 'default' | 'warn' | 'bad' }[] = [
  { key: '0-30', name: '0–30 days', tone: 'default' }, { key: '31-90', name: '31–90 days', tone: 'warn' }, { key: '90+', name: 'Over 90 days', tone: 'bad' },
];

const axisMoney = (v: number) => (v >= 1e7 ? `₹${(v / 1e7).toFixed(1)} Cr` : v >= 1e5 ? `₹${(v / 1e5).toFixed(1)} L` : `₹${Math.round(v)}`);

function LadderTooltip({ active, payload }: { active?: boolean; payload?: { payload: { name: string; minor: number } }[] }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow"><p className="font-semibold">{p.name}</p><p className="tabular-nums">{inr(p.minor)}</p></div>;
}

export default function PayablesInsights() {
  const { data, isLoading, error } = useApi<Insights>('/payables/insights');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="INV-04 · Payables insights" title="Payables insights"
        subtitle="What is due and when, how fast we pay, whether early-payment discounts are captured, how clean matching is, and how old the received-not-invoiced accruals are."
        actions={<>
          <LinkButton href="/pic/invoices">Invoices</LinkButton>
          <LinkButton href="/pic/invoices/reconciliation">Posting & reconciliation</LinkButton>
        </>} />

      {isLoading ? <Loading /> : error || !data ? <ProblemBox error={error} /> : <Body data={data} />}
    </div>
  );
}

function Body({ data }: { data: Insights }) {
  const bars = LADDER.map((b) => ({ ...b, value: data.dueLadderMinor[b.key] / 100, minor: data.dueLadderMinor[b.key] }));
  const totalDue = bars.reduce((s, b) => s + b.minor, 0);
  const grirTotal = AGEING.reduce((s, a) => s + data.grirAgeingMinor[a.key], 0);
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="DPO" value={data.dpoDays === null ? '–' : `${data.dpoDays} d`} hint="payment-weighted days from invoice date to value date" />
        <Kpi label="Discount capture" value={data.discountCapturePct === null ? '–' : `${data.discountCapturePct}%`}
          hint={data.discountNote ?? `${inr(data.discountCapturedMinor)} of ${inr(data.discountAvailableMinor)} available`}
          tone={data.discountCapturePct === null ? 'default' : Number(data.discountCapturePct) >= 80 ? 'good' : 'warn'} />
        <Kpi label="First-pass match" value={data.firstPassMatchPct === null ? '–' : `${data.firstPassMatchPct}%`} hint="invoices matched without an exception"
          tone={data.firstPassMatchPct === null ? 'default' : Number(data.firstPassMatchPct) >= 80 ? 'good' : 'warn'} />
        <Kpi label="Duplicates prevented" value={data.duplicatesPrevented} hint="blocked by the duplicate check before posting" tone={data.duplicatesPrevented ? 'good' : 'default'} />
      </div>

      <Card title="Due-date ladder · posted, unpaid invoices" actions={<span className="text-sm font-semibold tabular-nums">{inr(totalDue)}</span>}>
        {totalDue === 0 ? <Empty title="Nothing posted is waiting for payment" /> : (
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={bars} margin={{ top: 24, right: 12, bottom: 4, left: 8 }} barCategoryGap="28%">
                <CartesianGrid vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#334155' }} axisLine={{ stroke: '#cbd5e1' }} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} width={72} tickFormatter={axisMoney} />
                <Tooltip cursor={{ fill: '#f1f5f9' }} content={<LadderTooltip />} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={56}>
                  {bars.map((b) => <Cell key={b.key} fill={b.fill} />)}
                  <LabelList dataKey="minor" position="top" formatter={(v: unknown) => (Number(v) ? inr(Number(v)) : '')} style={{ fontSize: 11, fill: '#334155' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {data.discountNote && <p className="mt-3 text-xs text-slate-500">Discounts: {data.discountNote}.</p>}
      </Card>

      <Card title="GR/IR ageing · received, not yet invoiced" actions={<span className="text-sm font-semibold tabular-nums">{inr(grirTotal)}</span>}>
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {AGEING.map((a) => <Kpi key={a.key} label={a.name} value={inr(data.grirAgeingMinor[a.key])} tone={data.grirAgeingMinor[a.key] ? a.tone : 'default'} />)}
        </div>
        <DataTable<Accrual> rows={data.grir} empty="No open GR/IR balance" columns={[
          { key: 'po', header: 'PO', render: (r) => <Link href={`/pic/purchase-orders/${encodeURIComponent(r.po)}`} className="font-medium text-[#1A56DB] hover:underline">{r.po}</Link> },
          { key: 'line', header: 'Line', align: 'right' },
          { key: 'supplier', header: 'Supplier' },
          { key: 'ageDays', header: 'Age', align: 'right', render: (r) => `${Math.max(0, r.ageDays)} d` },
          { key: 'bucket', header: 'Bucket', render: (r) => <span className={r.bucket === '90+' ? 'font-semibold text-red-700' : r.bucket === '31-90' ? 'text-amber-700' : ''}>{r.bucket} d</span> },
          { key: 'accrualMinor', header: 'Accrual', align: 'right', render: (r) => inr(r.accrualMinor) },
        ]} />
      </Card>
    </>
  );
}
