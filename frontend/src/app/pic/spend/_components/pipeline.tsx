'use client';

import { useSearchParams } from 'next/navigation';
import { ReactNode, useEffect, useId, useState } from 'react';
import {
  Button,
  Card,
  DataTable,
  Dialog,
  Empty,
  Facts,
  Field,
  Input,
  Kpi,
  Loading,
  ProblemBox,
  Select,
  StatusChip,
  Textarea,
} from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { crore, date, dateTime, inr, label, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { useMe } from '../../mrp/_components';
import { ShareBar, SpendProblem } from './shared';

const STAGES = ['IDENTIFIED', 'NEGOTIATED', 'CONTRACTED', 'REALISING', 'VALIDATED', 'LOST'] as const;
type Stage = (typeof STAGES)[number];

const BASELINE_METHODS = [
  { value: 'LAST_PRICE', label: 'Last price paid' },
  { value: 'WAVG_12M', label: '12-month weighted average' },
  { value: 'STANDARD', label: 'Standard price (material master)' },
  { value: 'SHOULD_COST', label: 'Should-cost model baseline' },
];

type InitiativeRow = {
  id: string;
  number: string;
  title: string;
  category: string;
  stage: Stage;
  owner: string | null;
  ownerId: string;
  baselineMethod: string;
  forecastMinor: number;
  forecastBasis: string;
  negotiatedMinor: number;
  avoidanceMinor: number;
  realisedMinor: number;
  realisationPct: string | null;
  gapMinor: number;
  validated: boolean;
  createdAt: string;
};

type StageStat = {
  stage: Stage;
  count: number;
  forecastMinor: number;
  negotiatedMinor: number;
  avoidanceMinor: number;
  realisedMinor: number;
  realisationPct: string | null;
};

type PipelineTotals = {
  initiatives: number;
  forecastMinor: number;
  negotiatedMinor: number;
  avoidanceMinor: number;
  realisedMinor: number;
  lostMinor: number;
  realisationPct: string | null;
};

type PipelineData = {
  filters: Record<string, string>;
  stages: StageStat[];
  funnel: Record<string, number>;
  initiatives: InitiativeRow[];
  totals: PipelineTotals;
  categories: string[];
  owners: { id: string; name: string | null }[];
};

type WaterfallEntry = {
  type: string;
  amountMinor: number;
  countsTowardBudget: boolean;
  formula: string;
  source: string;
  date: string;
};

type LeakageItem = {
  po: string;
  kind: 'OFF_CONTRACT' | 'PRICE_DRIFT';
  amountMinor: number;
};

type WaterfallData = {
  initiative: string;
  stage: Stage;
  negotiatedMinor: number;
  contractedMinor: number;
  realisedMinor: number;
  avoidanceMinor: number;
  leakage: LeakageItem[];
  budgetImpactMinor: number;
  entries: WaterfallEntry[];
};

type PnlMonth = {
  period: string;
  realisedMinor: number;
  validatedMinor: number;
  pendingValidationMinor: number;
  negotiatedMinor: number;
  avoidanceMinor: number;
  cumulativeValidatedMinor: number;
};

type PnlCategory = {
  category: string;
  realisedMinor: number;
  validatedMinor: number;
  pendingValidationMinor: number;
  negotiatedMinor: number;
  avoidanceMinor: number;
  planBudgetMinor: number | null;
  planTargetMinor: number | null;
  attainmentPct: string | null;
};

type ValidationQueueItem = {
  id: string;
  number: string;
  title: string;
  category: string;
  stage: string;
  realisedMinor: number;
  owner: string | null;
  canValidate: boolean;
};

type PnlData = {
  fiscalYear: string;
  from: string;
  to: string;
  months: PnlMonth[];
  categories: PnlCategory[];
  totals: {
    realisedMinor: number;
    validatedMinor: number;
    pendingValidationMinor: number;
    negotiatedMinor: number;
    avoidanceMinor: number;
    budgetImpactMinor: number;
    planTargetMinor: number | null;
    attainmentPct: string | null;
  };
  validationQueue: ValidationQueueItem[];
  rule: string;
};

/**
 * SPD-08 Savings Pipeline Tracker:
 * Forecast vs realised savings and cost avoidance across initiatives and stages:
 * Identified -> Negotiated -> Contracted -> Realising -> Validated -> Lost.
 */
export function PipelineTab() {
  const searchParams = useSearchParams();
  const urlRef = searchParams.get('ref');
  const { roles, scopes, me } = useMe();
  const canManage = scopes.includes('savings:manage') || roles.some((r) => ['CATEGORY_MANAGER', 'PROCUREMENT_HEAD', 'CPO'].includes(r));
  const isFinance = roles.includes('FINANCE_CONTROLLER');

  // Filter state
  const [stageFilter, setStageFilter] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [ownerFilter, setOwnerFilter] = useState<string>('');
  const [minForecastRupees, setMinForecastRupees] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Dialog triggers
  const [openedRef, setOpenedRef] = useState<string | null>(null);
  const [negotiateRef, setNegotiateRef] = useState<InitiativeRow | null>(null);
  const [loseRef, setLoseRef] = useState<InitiativeRow | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState<boolean>(false);
  const [showPnlModal, setShowPnlModal] = useState<boolean>(false);

  // Auto-open if query param `ref` is present
  useEffect(() => {
    if (urlRef) {
      setOpenedRef(urlRef);
    }
  }, [urlRef]);

  // Construct query params for pipeline API
  const queryParts = new URLSearchParams();
  if (stageFilter) queryParts.set('stage', stageFilter);
  if (categoryFilter) queryParts.set('category', categoryFilter);
  if (ownerFilter) queryParts.set('owner', ownerFilter);
  if (minForecastRupees && Number(minForecastRupees) > 0) {
    queryParts.set('min_forecast_minor', String(rupeesToMinor(minForecastRupees)));
  }

  const { data, isLoading, error, refetch } = useApi<PipelineData>(`/savings/pipeline?${queryParts.toString()}`);

  const totals = data?.totals ?? {
    initiatives: 0,
    forecastMinor: 0,
    negotiatedMinor: 0,
    avoidanceMinor: 0,
    realisedMinor: 0,
    lostMinor: 0,
    realisationPct: null,
  };

  const rawInitiatives = data?.initiatives ?? [];
  const filteredInitiatives = rawInitiatives.filter((item) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return item.number.toLowerCase().includes(q) || item.title.toLowerCase().includes(q) || item.category.toLowerCase().includes(q);
  });

  const stagesList = data?.stages ?? [];
  const funnel = data?.funnel ?? {};

  return (
    <div className="space-y-6">
      {/* Overview & Quick Actions Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-3xl text-sm text-slate-600">
          Track savings initiatives from initial opportunity identification through negotiation, contract commitment, line-item invoice
          realisation, to final finance validation. Only finance-validated savings count toward budget impact (SOD-07).
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => setShowPnlModal(true)}>
            Savings P&L & Validation queue
          </Button>
          {canManage && (
            <Button variant="primary" onClick={() => setShowCreateDialog(true)}>
              + New initiative
            </Button>
          )}
        </div>
      </div>

      {isLoading ? (
        <Loading />
      ) : error ? (
        <SpendProblem error={error} permission="savings:manage" />
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Initiatives" value={totals.initiatives} hint={`${filteredInitiatives.length} visible`} />
            <Kpi label="Forecast Savings" value={inr(totals.forecastMinor)} hint="Pipeline projection" />
            <Kpi label="Negotiated" value={inr(totals.negotiatedMinor)} hint="Committed terms" />
            <Kpi
              label="Realised Savings"
              value={inr(totals.realisedMinor)}
              tone="good"
              hint={totals.realisationPct ? `${totals.realisationPct}% of negotiated` : 'Invoiced to date'}
            />
            <Kpi label="Cost Avoidance" value={inr(totals.avoidanceMinor)} hint="Prevented inflation" />
            <Kpi
              label="Lost Value"
              value={inr(totals.lostMinor)}
              tone={totals.lostMinor > 0 ? 'bad' : 'default'}
              hint="Unrealised / lapsed"
            />
          </div>

          {/* Pipeline Funnel & Stage Progression */}
          <Card
            title="Savings Funnel & Stage Breakdown"
            actions={
              stageFilter ? (
                <button
                  type="button"
                  onClick={() => setStageFilter('')}
                  className="text-xs font-semibold text-[#1A56DB] hover:underline"
                >
                  Clear stage filter ({label(stageFilter)})
                </button>
              ) : (
                <span className="text-xs text-slate-500">Click a stage card to filter</span>
              )
            }
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {STAGES.map((st) => {
                const stat = stagesList.find((s) => s.stage === st);
                const count = stat?.count ?? 0;
                const funnelCount = funnel[st] ?? count;
                const active = stageFilter === st;
                const isLost = st === 'LOST';

                return (
                  <button
                    key={st}
                    type="button"
                    onClick={() => setStageFilter(active ? '' : st)}
                    className={`flex flex-col justify-between rounded-lg border p-3.5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] ${active
                        ? 'border-[#1A56DB] bg-blue-50/60 ring-1 ring-[#1A56DB]'
                        : isLost
                          ? 'border-slate-200 bg-slate-50/50 hover:border-slate-300'
                          : 'border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/30'
                      }`}
                  >
                    <div>
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-xs font-semibold uppercase tracking-wider text-slate-600">{label(st)}</span>
                        <StatusChip status={st} />
                      </div>
                      <p className="mt-2 text-2xl font-bold tabular-nums text-slate-900">{count}</p>
                      {!isLost && (
                        <p className="text-[11px] text-slate-500">
                          {funnelCount} reached stage
                        </p>
                      )}
                    </div>
                    <div className="mt-3 border-t border-slate-100 pt-2 text-xs">
                      {st === 'IDENTIFIED' && (
                        <p className="tabular-nums text-slate-600">Forecast: {inr(stat?.forecastMinor ?? 0)}</p>
                      )}
                      {st === 'NEGOTIATED' && (
                        <p className="tabular-nums text-slate-600">Negotiated: {inr(stat?.negotiatedMinor ?? 0)}</p>
                      )}
                      {st === 'CONTRACTED' && (
                        <p className="tabular-nums text-slate-600">Contracted: {inr(stat?.negotiatedMinor ?? 0)}</p>
                      )}
                      {(st === 'REALISING' || st === 'VALIDATED') && (
                        <div>
                          <p className="tabular-nums text-emerald-700 font-medium">Realised: {inr(stat?.realisedMinor ?? 0)}</p>
                          {stat?.realisationPct && (
                            <p className="text-[11px] text-slate-500">{stat.realisationPct}% realised</p>
                          )}
                        </div>
                      )}
                      {isLost && (
                        <p className="tabular-nums text-red-700">Lost: {inr(stat?.forecastMinor ?? 0)}</p>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </Card>

          {/* Filter Bar */}
          <Card>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-5">
              <Field label="Search">
                {(id) => (
                  <Input
                    id={id}
                    placeholder="Search ID, title, or category…"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                )}
              </Field>

              <Field label="Stage">
                {(id) => (
                  <Select
                    id={id}
                    value={stageFilter}
                    onChange={(e) => setStageFilter(e.target.value)}
                    options={[
                      { value: '', label: 'All stages' },
                      ...STAGES.map((s) => ({ value: s, label: label(s) })),
                    ]}
                  />
                )}
              </Field>

              <Field label="Category">
                {(id) => (
                  <Select
                    id={id}
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    options={[
                      { value: '', label: 'All categories' },
                      ...(data?.categories ?? []).map((c) => ({ value: c, label: c })),
                    ]}
                  />
                )}
              </Field>

              <Field label="Owner">
                {(id) => (
                  <Select
                    id={id}
                    value={ownerFilter}
                    onChange={(e) => setOwnerFilter(e.target.value)}
                    options={[
                      { value: '', label: 'All owners' },
                      ...(data?.owners ?? []).map((o) => ({ value: o.id, label: o.name ?? o.id.slice(0, 8) })),
                    ]}
                  />
                )}
              </Field>

              <Field label="Min Forecast (₹)">
                {(id) => (
                  <Input
                    id={id}
                    type="number"
                    min="0"
                    placeholder="e.g. 500000"
                    value={minForecastRupees}
                    onChange={(e) => setMinForecastRupees(e.target.value)}
                  />
                )}
              </Field>
            </div>

            {(stageFilter || categoryFilter || ownerFilter || minForecastRupees || searchQuery) && (
              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
                <span>
                  Showing {filteredInitiatives.length} of {rawInitiatives.length} initiative(s)
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setStageFilter('');
                    setCategoryFilter('');
                    setOwnerFilter('');
                    setMinForecastRupees('');
                    setSearchQuery('');
                  }}
                  className="font-semibold text-[#1A56DB] hover:underline"
                >
                  Reset all filters
                </button>
              </div>
            )}
          </Card>

          {/* Initiatives Table */}
          <DataTable<InitiativeRow>
            empty="No savings initiatives match the selected filters"
            rows={filteredInitiatives as (InitiativeRow & Record<string, unknown>)[]}
            columns={[
              {
                key: 'number',
                header: 'Initiative',
                render: (row) => (
                  <div>
                    <button
                      type="button"
                      onClick={() => setOpenedRef(row.number)}
                      className="font-mono font-semibold text-[#1A56DB] hover:underline"
                    >
                      {row.number}
                    </button>
                    <p className="line-clamp-1 max-w-xs text-xs text-slate-600" title={row.title}>
                      {row.title}
                    </p>
                  </div>
                ),
              },
              {
                key: 'category',
                header: 'Category',
                render: (row) => <span className="font-medium text-slate-800">{row.category}</span>,
              },
              {
                key: 'stage',
                header: 'Stage',
                render: (row) => (
                  <div className="flex flex-col items-start gap-1">
                    <StatusChip status={row.stage} />
                    {row.validated && (
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">
                        Finance Validated
                      </span>
                    )}
                  </div>
                ),
              },
              {
                key: 'owner',
                header: 'Owner',
                render: (row) => <span className="text-slate-700">{row.owner ?? 'Unassigned'}</span>,
              },
              {
                key: 'baselineMethod',
                header: 'Baseline',
                render: (row) => (
                  <span className="text-xs text-slate-600" title={row.baselineMethod}>
                    {label(row.baselineMethod)}
                  </span>
                ),
              },
              {
                key: 'forecastMinor',
                header: 'Forecast',
                align: 'right',
                render: (row) => (
                  <div>
                    <p className="font-medium tabular-nums">{inr(row.forecastMinor)}</p>
                    <span className="font-mono text-[10px] uppercase text-slate-400">
                      basis: {row.forecastBasis.toLowerCase()}
                    </span>
                  </div>
                ),
              },
              {
                key: 'negotiatedMinor',
                header: 'Negotiated',
                align: 'right',
                render: (row) => <span className="tabular-nums">{inr(row.negotiatedMinor)}</span>,
              },
              {
                key: 'realisedMinor',
                header: 'Realised',
                align: 'right',
                render: (row) => (
                  <div>
                    <p className="font-semibold tabular-nums text-emerald-700">{inr(row.realisedMinor)}</p>
                    {row.realisationPct && (
                      <span className="text-xs tabular-nums text-slate-500">
                        {row.realisationPct}%
                      </span>
                    )}
                  </div>
                ),
              },
              {
                key: 'gapMinor',
                header: 'Gap',
                align: 'right',
                render: (row) => (
                  <span className={`tabular-nums ${row.gapMinor > 0 ? 'text-amber-700' : 'text-slate-400'}`}>
                    {inr(row.gapMinor)}
                  </span>
                ),
              },
              {
                key: 'actions',
                header: 'Actions',
                align: 'right',
                render: (row) => {
                  const isOwner = me?.user && (row.ownerId === me.user || row.owner === me.name);
                  const canNegotiate = (canManage || isOwner) && row.stage === 'IDENTIFIED';
                  const canLose = (canManage || isOwner) && !['LOST', 'VALIDATED'].includes(row.stage);

                  return (
                    <div className="flex items-center justify-end gap-1.5">
                      <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setOpenedRef(row.number)}>
                        Inspect
                      </Button>
                      {canNegotiate && (
                        <Button
                          variant="secondary"
                          className="!px-2 !py-1 text-xs"
                          onClick={() => setNegotiateRef(row)}
                        >
                          Negotiate
                        </Button>
                      )}
                      {canLose && (
                        <Button
                          variant="danger"
                          className="!px-2 !py-1 text-xs"
                          onClick={() => setLoseRef(row)}
                        >
                          Lose
                        </Button>
                      )}
                    </div>
                  );
                },
              },
            ]}
          />
        </>
      )}

      {/* Waterfall & Detail Dialog */}
      {openedRef && (
        <WaterfallDialog
          refNumber={openedRef}
          onClose={() => setOpenedRef(null)}
          onChanged={() => refetch()}
          isFinance={isFinance}
        />
      )}

      {/* Negotiate Action Dialog */}
      {negotiateRef && (
        <NegotiateDialog
          initiative={negotiateRef}
          onClose={() => setNegotiateRef(null)}
          onSuccess={() => {
            setNegotiateRef(null);
            refetch();
          }}
        />
      )}

      {/* Lose Action Dialog */}
      {loseRef && (
        <LoseDialog
          initiative={loseRef}
          onClose={() => setLoseRef(null)}
          onSuccess={() => {
            setLoseRef(null);
            refetch();
          }}
        />
      )}

      {/* Create Initiative Dialog */}
      {showCreateDialog && (
        <CreateInitiativeDialog
          categories={data?.categories ?? []}
          onClose={() => setShowCreateDialog(false)}
          onSuccess={(newRef) => {
            setShowCreateDialog(false);
            refetch();
            setOpenedRef(newRef);
          }}
        />
      )}

      {/* Savings P&L & Validation Queue Modal */}
      {showPnlModal && (
        <SavingsPnlModal
          onClose={() => setShowPnlModal(false)}
          onValidated={() => refetch()}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Detail & Waterfall Dialog
function WaterfallDialog({
  refNumber,
  onClose,
  onChanged,
  isFinance,
}: {
  refNumber: string;
  onClose: () => void;
  onChanged: () => void;
  isFinance: boolean;
}) {
  const { data, isLoading, error, refetch } = useApi<WaterfallData>(`/savings/${encodeURIComponent(refNumber)}/waterfall`);
  const validateCmd = useCommand(
    () => api.post(`/savings/${encodeURIComponent(refNumber)}/validate`, {}),
    {
      success: `${refNumber} validated by finance; realised savings now count toward fiscal year budget impact.`,
    }
  );

  async function handleValidate() {
    await validateCmd.mutateAsync();
    refetch();
    onChanged();
  }

  const d = data;
  const canValidateNow = isFinance && d?.stage === 'REALISING';

  return (
    <Dialog open wide title={`Initiative ${refNumber}`} onClose={onClose}>
      {isLoading ? (
        <Loading />
      ) : error ? (
        <ProblemBox error={error} />
      ) : !d ? (
        <Empty title="Initiative detail not available" />
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-slate-800">{d.initiative}</span>
              <StatusChip status={d.stage} />
            </div>
            {canValidateNow && (
              <Button
                variant="primary"
                busy={validateCmd.isPending}
                onClick={handleValidate}
              >
                Validate for budget impact (Finance sign-off)
              </Button>
            )}
          </div>

          {validateCmd.error && <ProblemBox error={validateCmd.error} />}

          {/* Metric Highlights */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Negotiated" value={inr(d.negotiatedMinor)} />
            <Kpi label="Contracted" value={inr(d.contractedMinor)} />
            <Kpi label="Realised to Date" value={inr(d.realisedMinor)} tone="good" />
            <Kpi
              label="Budget Impact"
              value={inr(d.budgetImpactMinor)}
              hint={d.stage === 'VALIDATED' ? 'Finance validated' : 'Pending validation'}
              tone={d.stage === 'VALIDATED' ? 'good' : 'default'}
            />
          </div>

          {/* Leakage Section */}
          {d.leakage && d.leakage.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-800">
                Leakage Detected ({d.leakage.length} purchase order lines)
              </h3>
              <p className="mt-0.5 text-xs text-amber-700">
                Purchases made off-contract or with pricing above agreed rates reduce expected value realisation.
              </p>
              <div className="mt-3 divide-y divide-amber-200/60 overflow-hidden rounded border border-amber-200 bg-white text-xs">
                {d.leakage.map((leak, idx) => (
                  <div key={idx} className="flex items-center justify-between px-3 py-2">
                    <span className="font-mono font-medium text-slate-800">{leak.po}</span>
                    <span className="rounded bg-amber-100 px-2 py-0.5 font-semibold text-amber-800">
                      {label(leak.kind)}
                    </span>
                    <span className="tabular-nums font-semibold text-red-600">
                      -{inr(leak.amountMinor)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Ledger Postings */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              Savings Ledger Postings ({d.entries?.length ?? 0})
            </h3>
            {!d.entries?.length ? (
              <Empty title="No postings recorded yet" hint="Postings appear as POs and invoices are processed against this initiative." />
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-xs">
                  <thead className="bg-slate-50 text-left uppercase tracking-wider text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Posting Date</th>
                      <th className="px-3 py-2">Type</th>
                      <th className="px-3 py-2">Source</th>
                      <th className="px-3 py-2">Formula / Basis</th>
                      <th className="px-3 py-2 text-right">Amount</th>
                      <th className="px-3 py-2 text-center">Budget Impact</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {d.entries.map((entry, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/50">
                        <td className="whitespace-nowrap px-3 py-2 text-slate-600">{date(entry.date)}</td>
                        <td className="px-3 py-2 font-medium">
                          <StatusChip status={entry.type} />
                        </td>
                        <td className="font-mono px-3 py-2 text-slate-700">{entry.source}</td>
                        <td className="px-3 py-2 font-mono text-slate-600">{entry.formula}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums text-slate-900">
                          {inr(entry.amountMinor)}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {entry.countsTowardBudget ? (
                            <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800">
                              Yes
                            </span>
                          ) : (
                            <span className="text-slate-400">No</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="flex justify-end border-t border-slate-100 pt-3">
            <Button onClick={onClose}>Close</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- Negotiate Dialog
function NegotiateDialog({
  initiative,
  onClose,
  onSuccess,
}: {
  initiative: InitiativeRow;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [newPriceRupees, setNewPriceRupees] = useState('');
  const [supplierCode, setSupplierCode] = useState('');
  const [evidence, setEvidence] = useState('');

  const cmd = useCommand(
    () =>
      api.post(`/savings/${encodeURIComponent(initiative.number)}/negotiate`, {
        new_price_minor: rupeesToMinor(newPriceRupees),
        supplier: supplierCode.trim(),
        evidence: evidence.trim(),
      }),
    {
      success: `Negotiated price recorded for ${initiative.number}`,
    }
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!newPriceRupees || !supplierCode || !evidence) return;
    await cmd.mutateAsync();
    onSuccess();
  }

  return (
    <Dialog open title={`Record Negotiated Terms: ${initiative.number}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-xs text-slate-600">
          Record the negotiated unit price with the supplier. This transitions the initiative to{' '}
          <strong>NEGOTIATED</strong> and computes committed annual savings against the baseline price.
        </p>

        {cmd.error && <ProblemBox error={cmd.error} />}

        <Field label="New Unit Price (₹)" required>
          {(id) => (
            <Input
              id={id}
              type="number"
              step="0.01"
              min="0.01"
              required
              placeholder="e.g. 42.50"
              value={newPriceRupees}
              onChange={(e) => setNewPriceRupees(e.target.value)}
            />
          )}
        </Field>

        <Field label="Supplier Code" hint="Primary awarded or renegotiated supplier" required>
          {(id) => (
            <Input
              id={id}
              required
              placeholder="e.g. SUP-0042"
              value={supplierCode}
              onChange={(e) => setSupplierCode(e.target.value)}
            />
          )}
        </Field>

        <Field label="Evidence / Negotiation Summary" hint="Reference RFQ, counter-offer, or agreement context" required>
          {(id) => (
            <Textarea
              id={id}
              required
              rows={3}
              placeholder="e.g. Agreed 8% price discount on corrugated boxes under revised 1-year volume commitment."
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
            />
          )}
        </Field>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose} disabled={cmd.isPending}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" busy={cmd.isPending}>
            Record Negotiation
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Lose Dialog
function LoseDialog({
  initiative,
  onClose,
  onSuccess,
}: {
  initiative: InitiativeRow;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [reason, setReason] = useState('');

  const cmd = useCommand(
    () =>
      api.post(`/savings/${encodeURIComponent(initiative.number)}/lose`, {
        reason: reason.trim(),
      }),
    {
      success: `${initiative.number} marked as lost`,
    }
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) return;
    await cmd.mutateAsync();
    onSuccess();
  }

  return (
    <Dialog open title={`Record Opportunity Loss: ${initiative.number}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-xs text-slate-600">
          Marking an initiative as lost stops tracking and excludes it from future active pipeline forecasts.
        </p>

        {cmd.error && <ProblemBox error={cmd.error} />}

        <Field label="Loss Reason" hint="Explain why savings could not be secured" required>
          {(id) => (
            <Textarea
              id={id}
              required
              rows={3}
              placeholder="e.g. Supplier rejected price concession due to raw material index escalation; alternative supplier failed quality qualification."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </Field>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose} disabled={cmd.isPending}>
            Cancel
          </Button>
          <Button variant="danger" type="submit" busy={cmd.isPending}>
            Mark as Lost
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Create Initiative Dialog
function CreateInitiativeDialog({
  categories,
  onClose,
  onSuccess,
}: {
  categories: string[];
  onClose: () => void;
  onSuccess: (newNumber: string) => void;
}) {
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState(categories[0] ?? 'PACKAGING');
  const [customCategory, setCustomCategory] = useState('');
  const [baselineMethod, setBaselineMethod] = useState('LAST_PRICE');
  const [annualVolume, setAnnualVolume] = useState('');
  const [materialNumber, setMaterialNumber] = useState('');
  const [baselinePriceRupees, setBaselinePriceRupees] = useState('');

  const cmd = useCommand(
    () =>
      api.post<{ number: string }>('/savings/initiatives', {
        title: title.trim(),
        category: category === '__custom__' ? customCategory.trim() : category,
        baseline_method: baselineMethod,
        annual_volume: Number(annualVolume),
        material: materialNumber.trim() || undefined,
        baseline_price_minor: baselinePriceRupees ? rupeesToMinor(baselinePriceRupees) : undefined,
      }),
    {
      success: (r) => `Savings initiative ${r.number} created in IDENTIFIED stage`,
    }
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title || !annualVolume) return;
    const res = await cmd.mutateAsync();
    if (res?.number) {
      onSuccess(res.number);
    }
  }

  const categoryOptions = [
    ...categories.map((c) => ({ value: c, label: c })),
    { value: '__custom__', label: '+ Enter custom category…' },
  ];

  return (
    <Dialog open wide title="Create Savings Initiative (SAV-01)" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-xs text-slate-600">
          Create a governed savings initiative. Baseline price is locked upon creation from the selected method (Blueprint §26).
        </p>

        {cmd.error && <ProblemBox error={cmd.error} />}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Initiative Title" required>
            {(id) => (
              <Input
                id={id}
                required
                placeholder="e.g. Masterbatch dual-sourcing & volume aggregation"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            )}
          </Field>

          <Field label="Category" required>
            {(id) => (
              <div className="space-y-1.5">
                <Select
                  id={id}
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  options={categoryOptions}
                />
                {category === '__custom__' && (
                  <Input
                    placeholder="Enter category name…"
                    required
                    value={customCategory}
                    onChange={(e) => setCustomCategory(e.target.value)}
                  />
                )}
              </div>
            )}
          </Field>

          <Field label="Baseline Method" hint="How pre-initiative baseline price is derived" required>
            {(id) => (
              <Select
                id={id}
                value={baselineMethod}
                onChange={(e) => setBaselineMethod(e.target.value)}
                options={BASELINE_METHODS}
              />
            )}
          </Field>

          <Field label="Estimated Annual Volume" hint="Units consumed per 12 months" required>
            {(id) => (
              <Input
                id={id}
                type="number"
                step="any"
                min="0.001"
                required
                placeholder="e.g. 50000"
                value={annualVolume}
                onChange={(e) => setAnnualVolume(e.target.value)}
              />
            )}
          </Field>

          <Field label="Material Number (optional)" hint="Required for standard price or last purchase order history">
            {(id) => (
              <Input
                id={id}
                placeholder="e.g. MAT-RAW-0012"
                value={materialNumber}
                onChange={(e) => setMaterialNumber(e.target.value)}
              />
            )}
          </Field>

          <Field
            label="Baseline Price in ₹ (optional)"
            hint={baselineMethod === 'SHOULD_COST' ? 'Required for Should-Cost model' : 'Overrides auto-derivation if supplied'}
            required={baselineMethod === 'SHOULD_COST'}
          >
            {(id) => (
              <Input
                id={id}
                type="number"
                step="0.01"
                min="0.01"
                required={baselineMethod === 'SHOULD_COST'}
                placeholder="e.g. 185.00"
                value={baselinePriceRupees}
                onChange={(e) => setBaselinePriceRupees(e.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <Button type="button" onClick={onClose} disabled={cmd.isPending}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" busy={cmd.isPending}>
            Create Initiative
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Savings P&L & Finance Validation Modal
function SavingsPnlModal({
  onClose,
  onValidated,
}: {
  onClose: () => void;
  onValidated: () => void;
}) {
  const [fiscalYear, setFiscalYear] = useState('2026-27');
  const { data, isLoading, error, refetch } = useApi<PnlData>(`/savings/pnl?fiscal_year=${fiscalYear}`);

  const validateCmd = useCommand(
    (ref: string) => api.post(`/savings/${encodeURIComponent(ref)}/validate`, {}),
    {
      success: 'Initiative validated by finance for budget impact.',
    }
  );

  async function handleValidate(ref: string) {
    await validateCmd.mutateAsync(ref);
    refetch();
    onValidated();
  }

  const d = data;
  const queue = d?.validationQueue ?? [];

  return (
    <Dialog open wide title="Savings P&L & Finance Validation Queue (M11-C4)" onClose={onClose}>
      {isLoading ? (
        <Loading />
      ) : error ? (
        <ProblemBox error={error} />
      ) : !d ? (
        <Empty title="No P&L data found" />
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3">
            <p className="max-w-xl text-xs text-slate-600">
              {d.rule}
            </p>
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-slate-700">Fiscal Year:</span>
              <select
                value={fiscalYear}
                onChange={(e) => setFiscalYear(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-[#1A56DB]"
              >
                <option value="2026-27">FY 2026-27</option>
                <option value="2025-26">FY 2025-26</option>
                <option value="2024-25">FY 2024-25</option>
              </select>
            </div>
          </div>

          {validateCmd.error && <ProblemBox error={validateCmd.error} />}

          {/* Budget Impact KPIs */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi
              label="Validated Budget Impact"
              value={crore(d.totals.budgetImpactMinor)}
              tone="good"
              hint={d.totals.attainmentPct ? `${d.totals.attainmentPct}% of target` : 'Reduces P&L budget'}
            />
            <Kpi
              label="Plan Savings Target"
              value={d.totals.planTargetMinor ? crore(d.totals.planTargetMinor) : '–'}
              hint="Approved plans target"
            />
            <Kpi
              label="Pending Finance Sign-off"
              value={crore(d.totals.pendingValidationMinor)}
              tone="warn"
              hint={`${queue.length} in queue`}
            />
            <Kpi
              label="Total Realised on Invoices"
              value={crore(d.totals.realisedMinor)}
              hint="Booked ledger total"
            />
          </div>

          {/* Finance Validation Queue Table */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                Finance Validation Queue ({queue.length})
              </h3>
              <span className="text-[11px] text-slate-500">
                SOD-07: Finance controllers approve; owners cannot validate own initiatives
              </span>
            </div>

            {!queue.length ? (
              <Empty title="Validation queue is clear" hint="All currently realised initiatives have been signed off by finance." />
            ) : (
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-xs">
                  <thead className="bg-slate-50 text-left uppercase tracking-wider text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Initiative</th>
                      <th className="px-3 py-2">Title</th>
                      <th className="px-3 py-2">Category</th>
                      <th className="px-3 py-2">Owner</th>
                      <th className="px-3 py-2 text-right">Realised to Date</th>
                      <th className="px-3 py-2 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {queue.map((item) => (
                      <tr key={item.id} className="hover:bg-slate-50/50">
                        <td className="font-mono px-3 py-2 font-semibold text-[#1A56DB]">{item.number}</td>
                        <td className="px-3 py-2 font-medium text-slate-900">{item.title}</td>
                        <td className="px-3 py-2 text-slate-700">{item.category}</td>
                        <td className="px-3 py-2 text-slate-600">{item.owner ?? '–'}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums text-emerald-700">
                          {inr(item.realisedMinor)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right">
                          <Button
                            variant="primary"
                            className="!px-2.5 !py-1 text-xs"
                            busy={validateCmd.isPending}
                            disabled={!item.canValidate}
                            onClick={() => handleValidate(item.number)}
                            title={!item.canValidate ? 'Only finance controllers who do not own this initiative can validate (SOD-07)' : 'Validate'}
                          >
                            Sign off (Validate)
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Category Attainment Table */}
          {d.categories && d.categories.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                Category Savings Attainment
              </h3>
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200 text-xs">
                  <thead className="bg-slate-50 text-left uppercase tracking-wider text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Category</th>
                      <th className="px-3 py-2 text-right">Realised</th>
                      <th className="px-3 py-2 text-right">Validated</th>
                      <th className="px-3 py-2 text-right">Savings Target</th>
                      <th className="px-3 py-2 text-right">Attainment %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {d.categories.map((cat, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/50">
                        <td className="px-3 py-2 font-medium text-slate-900">{cat.category}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-700">
                          {inr(cat.realisedMinor)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums text-emerald-700">
                          {inr(cat.validatedMinor)}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-500">
                          {cat.planTargetMinor ? inr(cat.planTargetMinor) : '–'}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums font-semibold">
                          {cat.attainmentPct ? `${cat.attainmentPct}%` : '–'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="flex justify-end border-t border-slate-100 pt-3">
            <Button onClick={onClose}>Close</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}

