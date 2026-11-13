'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Card,
  CopyButton,
  FilterPills,
  Kpi,
  Loading,
  PageHeader,
  ProblemBox,
  StatusChip,
} from '@/components/pic/ui';
import { useLive } from '@/components/pic/WorkspaceShell';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Filter,
  Layers,
  Pause,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
} from 'lucide-react';

type Dashboard = {
  asOf: string;
  spend: { totalMinor: number; contractCoveragePct: string | null; maverickPct: string | null };
  purchasing: { touchlessPct: string | null; released: number; byStatus: Record<string, number> };
  requisitions: { byStatus: Record<string, number>; avgApprovalHours: string | null };
  payables: { firstPassMatchPct: string | null; byStatus: Record<string, number>; openExceptions: number; paymentBlocked: number };
  savings: { negotiatedCr: string; avoidanceCr: string; realisedCr: string };
  suppliers: { total: number; categoryStatus: Record<string, number>; qualifiedCoveragePct: string | null };
  integration: { byStatus: Record<string, number>; postingSuccessPct: string | null };
  controls: { sodViolations: number; agentRuns: number };
  tasks: { open: number; overdue: number; mine: number };
  activity: { ts: string; objectType: string; objectRef: string; action: string; actor: string }[];
};

type ViewCategory = 'all' | 'procurement' | 'finance' | 'governance';

function StatusCounts({ counts, targetPath }: { counts: Record<string, number>; targetPath?: string }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <p className="text-sm text-ink-3">None yet</p>;
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-2">
        {entries.map(([s, n]) => (
          <li key={s} className="group flex items-center gap-1.5 transition-transform hover:scale-105">
            {targetPath ? (
              <Link href={`${targetPath}?status=${s}`} className="focus:outline-none focus-visible:ring-1 focus-visible:ring-brand rounded-full">
                <StatusChip status={s} />
              </Link>
            ) : (
              <StatusChip status={s} />
            )}
            <span className="text-sm font-semibold tabular-nums text-ink">{n}</span>
          </li>
        ))}
      </ul>
      {targetPath && (
        <div className="flex justify-end pt-1">
          <Link
            href={targetPath}
            className="inline-flex items-center gap-1 text-xs font-medium text-brand-ink hover:underline"
          >
            <span>View worklist</span>
            <ArrowRight size={12} />
          </Link>
        </div>
      )}
    </div>
  );
}

export default function CommandCentre() {
  const { data, isLoading, error } = useApi<Dashboard>('/dashboard');
  const live = useLive();
  const [activeTab, setActiveTab] = useState<ViewCategory>('all');
  const [liveSearch, setLiveSearch] = useState('');
  const [isStreamPaused, setIsStreamPaused] = useState(false);

  // Parse percentages safely
  const parsePct = (v: string | null) => (v ? parseFloat(v) : 0);
  const pctStr = (v: string | null) => (v === null ? '–' : `${v}%`);

  // Filtered live events
  const filteredEvents = useMemo(() => {
    if (!live.events.length) return [];
    if (!liveSearch.trim()) return live.events;
    const q = liveSearch.toLowerCase();
    return live.events.filter(
      (e) =>
        e.type.toLowerCase().includes(q) ||
        e.ref.toLowerCase().includes(q) ||
        e.actor.toLowerCase().includes(q)
    );
  }, [live.events, liveSearch]);

  if (isLoading) return <Loading text="Initializing Command Centre intelligence feed..." />;
  if (error || !data) return <ProblemBox error={error} />;

  const touchlessNum = parsePct(data.purchasing.touchlessPct);
  const matchNum = parsePct(data.payables.firstPassMatchPct);
  const contractNum = parsePct(data.spend.contractCoveragePct);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AIX-01 · Procurement Command Flight Deck"
        title={
          <span className="flex items-center gap-2.5">
            <span>Command Centre</span>
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              Live Telemetry
            </span>
          </span>
        }
        subtitle={
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>Live from posted transactions · Singapore AWS · as of {dateTime(data.asOf)}.</span>
            <span className="text-ink-3">Realised savings benchmarked against approved invoices.</span>
          </div>
        }
        actions={
          <div className="flex items-center gap-2">
            <FilterPills<ViewCategory>
              active={activeTab}
              onChange={setActiveTab}
              options={[
                { id: 'all', label: 'All Operations' },
                { id: 'procurement', label: 'Procurement Ops' },
                { id: 'finance', label: 'Finance & AP' },
                { id: 'governance', label: 'Risk & Controls' },
              ]}
            />
          </div>
        }
      />

      {/* Primary KPI Command Tiles with Interactive Progress Bars & Click-throughs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="My Open Tasks"
          value={data.tasks.mine}
          hint={
            <span className="flex items-center justify-between text-xs">
              <span>{data.tasks.open} total open</span>
              <span className="text-brand-ink font-semibold">Review →</span>
            </span>
          }
          tone={data.tasks.mine > 0 ? 'warn' : 'default'}
          trend={data.tasks.mine > 0 ? { value: 'Requires Action', positive: false } : { value: 'All Clear', positive: true }}
          href="/pic/tasks"
        />

        <Kpi
          label="Posted Spend"
          value={inr(data.spend.totalMinor)}
          hint={`Contracted ${pctStr(data.spend.contractCoveragePct)}`}
          progress={contractNum}
          trend={{ value: `${data.spend.contractCoveragePct || 0}% covered`, positive: contractNum >= 75 }}
          href="/pic/spend"
        />

        <Kpi
          label="Touchless PO"
          value={pctStr(data.purchasing.touchlessPct)}
          hint={`${data.purchasing.released} released to date`}
          tone="good"
          progress={touchlessNum}
          trend={{ value: 'Target ≥ 85%', positive: touchlessNum >= 85, neutral: touchlessNum < 85 }}
          href="/pic/purchase-orders"
        />

        <Kpi
          label="First-Pass Match"
          value={pctStr(data.payables.firstPassMatchPct)}
          hint={`${data.payables.openExceptions} open exceptions`}
          progress={matchNum}
          tone={matchNum >= 90 ? 'good' : 'warn'}
          trend={{ value: 'Target ≥ 90%', positive: matchNum >= 90 }}
          href="/pic/invoices"
        />

        <Kpi
          label="Negotiated Savings"
          value={`₹${data.savings.negotiatedCr} Cr`}
          hint={`Avoidance ₹${data.savings.avoidanceCr} Cr`}
          tone="good"
          trend={{ value: 'FY 2026', positive: true }}
          href="/pic/savings"
        />

        <Kpi
          label="Realised Savings"
          value={`₹${data.savings.realisedCr} Cr`}
          hint="Cash settled & matched"
          tone="good"
          trend={{ value: 'Audited', positive: true }}
          href="/pic/savings"
        />
      </div>

      {/* Operational Module Cards (Filtered by Active Tab) */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {(activeTab === 'all' || activeTab === 'procurement') && (
          <Card
            title={
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-brand/10 text-brand-ink text-xs font-bold">PO</span>
                <span>Purchase Orders</span>
              </div>
            }
            interactive
            actions={
              <Link href="/pic/purchase-orders" className="text-xs font-semibold text-brand-ink hover:underline">
                View all →
              </Link>
            }
          >
            <StatusCounts counts={data.purchasing.byStatus} targetPath="/pic/purchase-orders" />
          </Card>
        )}

        {(activeTab === 'all' || activeTab === 'procurement') && (
          <Card
            title={
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-brand/10 text-brand-ink text-xs font-bold">PR</span>
                <span>Requisitions</span>
              </div>
            }
            interactive
            actions={
              <span className="rounded bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-ink-3">
                Avg cycle: {data.requisitions.avgApprovalHours ?? '–'} h
              </span>
            }
          >
            <StatusCounts counts={data.requisitions.byStatus} targetPath="/pic/requisitions" />
          </Card>
        )}

        {(activeTab === 'all' || activeTab === 'finance') && (
          <Card
            title={
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-brand/10 text-brand-ink text-xs font-bold">AP</span>
                <span>Invoices & 3-Way Match</span>
              </div>
            }
            interactive
            actions={
              <span className="rounded bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-400">
                {data.payables.paymentBlocked} on payment block
              </span>
            }
          >
            <StatusCounts counts={data.payables.byStatus} targetPath="/pic/invoices" />
          </Card>
        )}

        {(activeTab === 'all' || activeTab === 'governance') && (
          <Card
            title={
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-brand/10 text-brand-ink text-xs font-bold">SR</span>
                <span>Suppliers by Category</span>
              </div>
            }
            interactive
            actions={
              <span className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-3">
                Qualified {pctStr(data.suppliers.qualifiedCoveragePct)}
              </span>
            }
          >
            <StatusCounts counts={data.suppliers.categoryStatus} targetPath="/pic/suppliers" />
          </Card>
        )}

        {(activeTab === 'all' || activeTab === 'governance') && (
          <Card
            title={
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-brand/10 text-brand-ink text-xs font-bold">ERP</span>
                <span>ERP Connectors (S/4, Oracle)</span>
              </div>
            }
            interactive
            actions={
              <span className="rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400">
                {pctStr(data.integration.postingSuccessPct)} sync rate
              </span>
            }
          >
            <StatusCounts counts={data.integration.byStatus} targetPath="/pic/admin/connectors" />
          </Card>
        )}

        {(activeTab === 'all' || activeTab === 'governance') && (
          <Card
            title={
              <div className="flex items-center gap-2">
                <ShieldAlert size={16} className="text-brand-ink" />
                <span>Controls & Governance</span>
              </div>
            }
            interactive
            actions={
              <Link href="/pic/tasks" className="text-xs font-semibold text-brand-ink hover:underline">
                Resolve →
              </Link>
            }
          >
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <div className="rounded-xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface-2/60 p-3 transition hover:border-line-strong hover:bg-surface-2">
                <dt className="text-[11px] font-bold uppercase tracking-wider text-ink-3">Open tasks</dt>
                <dd className="mt-1 text-2xl font-extrabold tabular-nums text-ink">{data.tasks.open}</dd>
              </div>
              <div className="rounded-xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface-2/60 p-3 transition hover:border-line-strong hover:bg-surface-2">
                <dt className="text-[11px] font-bold uppercase tracking-wider text-ink-3">Overdue SLA</dt>
                <dd className={`mt-1 text-2xl font-extrabold tabular-nums ${data.tasks.overdue ? 'text-amber-600 dark:text-amber-400' : 'text-ink'}`}>
                  {data.tasks.overdue}
                </dd>
              </div>
              <div className="rounded-xl border border-line-strong/80 ring-1 ring-inset ring-black/[0.04] dark:ring-white/[0.06] bg-surface-2/60 p-3 transition hover:border-line-strong hover:bg-surface-2">
                <dt className="text-[11px] font-bold uppercase tracking-wider text-ink-3">SoD blocks</dt>
                <dd className={`mt-1 text-2xl font-extrabold tabular-nums ${data.controls.sodViolations ? 'text-red-600 dark:text-red-400' : 'text-ink'}`}>
                  {data.controls.sodViolations}
                </dd>
              </div>
            </dl>
          </Card>
        )}
      </div>

      {/* Live Stream Telemetry & Immutable Audit Trail */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Live Streaming Events */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-brand-ink animate-pulse" />
              <span>Live Events Stream</span>
            </div>
          }
          actions={
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search size={12} className="absolute left-2 top-2 text-ink-3" />
                <input
                  type="text"
                  placeholder="Filter events..."
                  value={liveSearch}
                  onChange={(e) => setLiveSearch(e.target.value)}
                  className="rounded-lg border border-line bg-surface-2 pl-6 pr-2 py-0.5 text-xs text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-brand"
                />
              </div>
              <button
                type="button"
                onClick={() => setIsStreamPaused((p) => !p)}
                className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-0.5 text-xs text-ink-2 hover:bg-surface-3 transition"
                title={isStreamPaused ? 'Resume stream updates' : 'Pause stream view'}
              >
                {isStreamPaused ? <Play size={11} className="text-emerald-500" /> : <Pause size={11} />}
                <span>{isStreamPaused ? 'Resume' : 'Pause'}</span>
              </button>
            </div>
          }
        >
          {filteredEvents.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-sm font-medium text-ink-2">
                {live.events.length === 0 ? 'No events streamed yet' : 'No events match your filter'}
              </p>
              <p className="mt-1 text-xs text-ink-3">
                Events appear in real-time as users and autonomous agents execute releases, receipts, and postings.
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-line text-sm max-h-[300px] overflow-y-auto pr-1">
              {filteredEvents.map((e) => (
                <li key={e.id} className="group flex flex-wrap items-center justify-between gap-2 py-2 hover:bg-surface-2/60 rounded px-1 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-brand-ink">{e.type}</span>
                    <span className="text-ink font-mono text-xs">· {e.ref}</span>
                    <CopyButton text={e.ref} />
                  </div>
                  <div className="flex items-center gap-2 text-xs text-ink-3">
                    <span className="font-medium text-ink-2">{e.actor}</span>
                    <span>·</span>
                    <span>{dateTime(e.at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Immutable Audit Log */}
        <Card
          title={
            <div className="flex items-center gap-2">
              <CheckCircle2 size={16} className="text-emerald-500" />
              <span>Immutable Activity & Audit Trail</span>
            </div>
          }
          actions={
            <span className="rounded bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-ink-3">
              Cryptographic chain
            </span>
          }
        >
          <ul className="divide-y divide-line text-sm max-h-[300px] overflow-y-auto pr-1">
            {data.activity.map((a, i) => (
              <li key={i} className="group flex flex-wrap items-center justify-between gap-2 py-2 hover:bg-surface-2/60 rounded px-1 transition-colors">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold text-ink">{a.objectRef ?? a.objectType}</span>
                  <span className="text-xs text-ink-2">· {label(a.action)}</span>
                  {a.objectRef && <CopyButton text={a.objectRef} />}
                </div>
                <div className="flex items-center gap-2 text-xs text-ink-3">
                  <span className="font-medium text-ink-2">{a.actor}</span>
                  <span>·</span>
                  <span>{dateTime(a.ts)}</span>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
