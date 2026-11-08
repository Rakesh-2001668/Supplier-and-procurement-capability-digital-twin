'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { AuditTrail, LineageView, ProcessPath } from '@/components/pic/object';
import { Button, Card, DataTable, Empty, Facts, Loading, ProblemBox, StatusChip, Tabs } from '@/components/pic/ui';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useList } from '@/lib/pic/hooks';
import { api } from '@/lib/pic/api';
import { PlannedOrder, PlannedOrderActions, ReasonDialog, SourceSummary, useMe } from '../_components';

type NetResult = {
  material: string; plant: string; gross: string; on_hand: string; open_po: string; in_transit: string; firm_receipts: string;
  open_req?: string; safety_stock: string; net: string;
  proposals: { qty: string; net: string; need_date: string; release_date: string }[];
  exceptions: { code: string; message: string; action: string }[];
};
type MrpException = { id: string; material_id: string; planned_order_id: string | null; code: string; message: string;
  value_at_risk_minor: number; recommended_action: string; status: string; created_at: string; close_reason?: string | null };
type Run = {
  id: string; number: string; mode: string; plant: string; scope: { materials?: string[] }; run_date: string; status: string;
  materials_planned: number; planned_orders_created: number; exceptions_raised: number; results: NetResult[] | null;
  created_at: string; completed_at: string | null; plannedOrders?: PlannedOrder[];
  /** 'summary' for a large run: counts only, the lists are read page by page (planned orders, exceptions, netting trace). */
  detail?: 'full' | 'summary'; resultsCount?: number;
};
type ExceptionPage = { items: MrpException[]; total: number; nextOffset: number | null };
type ResultPage = { items: NetResult[]; total: number; nextOffset: number | null };
type Material = { id: string; number: string; description: string };

export default function MrpRunPage() {
  const { ref } = useParams<{ ref: string }>();
  const { data: run, isLoading, error } = useApi<Run>(`/mrp/runs/${encodeURIComponent(ref)}`);
  const summary = run?.detail === 'summary';
  const [exceptionOffset, setExceptionOffset] = useState(0);
  const [resultOffset, setResultOffset] = useState(0);
  const exceptionsFull = useApi<MrpException[]>(run && !summary ? `/mrp/runs/${encodeURIComponent(run.number)}/exceptions` : null);
  const exceptionsPage = useApi<ExceptionPage>(run && summary ? `/mrp/runs/${encodeURIComponent(run.number)}/exceptions?limit=50&offset=${exceptionOffset}` : null);
  const resultsPage = useApi<ResultPage>(run && summary ? `/mrp/runs/${encodeURIComponent(run.number)}/results?limit=25&offset=${resultOffset}` : null);
  const exceptions = summary ? { data: exceptionsPage.data?.items, isLoading: exceptionsPage.isLoading, error: exceptionsPage.error } : exceptionsFull;
  // Planned orders and exceptions of the run carry material ids only; resolve them to material numbers.
  const materials = useApi<{ items: Material[] }>('/materials?limit=200');
  const materialNo = (id: string) => materials.data?.items.find((m) => m.id === id)?.number ?? '…';
  const { scopes } = useMe();
  const [closing, setClosing] = useState<MrpException | null>(null);

  if (isLoading) return <Loading />;
  if (error || !run) return <ProblemBox error={error} />;
  const results = summary ? (resultsPage.data?.items ?? []) : (run.results ?? []);
  const orders = run.plannedOrders ?? [];

  return (
    <div className="space-y-5">
      <div>
        <p className="font-mono text-xs uppercase tracking-wider text-slate-500">MRP-02 · MRP run</p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-[#0B1020]">{run.number} <span className="text-base font-normal text-slate-500">{label(run.mode)} · plant {run.plant}</span></h1>
          <StatusChip status={run.status} />
        </div>
      </div>

      <Card>
        <Facts items={[
          ['Mode', label(run.mode)], ['Plant', run.plant], ['Run date', date(run.run_date)],
          ['Scope', run.scope?.materials?.length ? run.scope.materials.join(', ') : 'All MRP-planned materials'],
          ['Materials planned', run.materials_planned], ['Planned orders created', run.planned_orders_created],
          ['Exceptions raised', run.exceptions_raised], ['Completed', dateTime(run.completed_at)],
        ]} />
        {run.status === 'SIMULATED' && <p className="mt-3 text-sm text-amber-700">Simulation run: the netting below is a report only; no planned orders or exceptions were saved.</p>}
      </Card>

      <Card title="Netting trace (MRP-02)">
        <p className="mb-3 text-sm text-slate-600">Net requirement = gross − (on hand + open PO + in transit + firm receipts + open requisitions) + safety stock. Positive net requirements are lot-sized into proposals.</p>
        {summary && <p className="mb-3 text-sm text-slate-600">Large run: {run.resultsCount} material(s) netted, shown 25 at a time.</p>}
        {!results.length ? <Empty title="No materials were in scope for this run" hint={run.mode === 'NET_CHANGE' ? 'Net-change runs only plan materials whose demand or supply changed since the last run.' : undefined} /> : (
          <div className="space-y-3">
            {results.map((r) => <NettingRow key={`${r.material}-${r.plant}`} r={r} />)}
            {summary && (
              <div className="flex gap-2">
                <Button disabled={resultOffset === 0} onClick={() => setResultOffset(Math.max(0, resultOffset - 25))}>Previous</Button>
                <Button disabled={!resultsPage.data?.nextOffset} onClick={() => setResultOffset(resultsPage.data?.nextOffset ?? resultOffset)}>Next</Button>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card>
        <Tabs tabs={[
          { id: 'orders', label: `Planned orders (${summary ? run.planned_orders_created : orders.length})`, content: summary ? (
            <SummaryOrders run={run} canPlan={scopes.includes('mrp:plan')} />
          ) : (
            <DataTable<PlannedOrder>
              rows={orders} empty={run.status === 'SIMULATED' ? 'Simulation runs create no planned orders' : 'No planned orders from this run'}
              columns={[
                { key: 'number', header: 'Planned order', render: (o) => <span className="font-medium">{o.number}</span> },
                { key: 'material_id', header: 'Material', render: (o) => o.material ?? materialNo(o.material_id) },
                { key: 'qty', header: 'Quantity', align: 'right', render: (o) => qty(o.qty) },
                { key: 'release_date', header: 'Release', render: (o) => date(o.release_date) },
                { key: 'need_date', header: 'Need', render: (o) => date(o.need_date) },
                { key: 'source', header: 'Source determination', render: (o) => <SourceSummary source={o.source} /> },
                { key: 'status', header: 'Status', render: (o) => <StatusChip status={o.status} /> },
                { key: 'actions', header: 'Actions', render: (o) => <PlannedOrderActions order={o} canPlan={scopes.includes('mrp:plan')} /> },
              ]}
            />
          ) },
          { id: 'exceptions', label: `Exceptions (${summary ? run.exceptions_raised : (exceptions.data?.length ?? run.exceptions_raised)})`, content: (
            <div className="space-y-2">
            <DataTable<MrpException>
              rows={exceptions.data ?? []} loading={exceptions.isLoading} error={exceptions.error} empty="No exceptions raised"
              columns={[
                { key: 'code', header: 'Exception', render: (e) => <span className="font-medium">{label(e.code)}</span> },
                { key: 'material_id', header: 'Material', render: (e) => materialNo(e.material_id) },
                { key: 'message', header: 'Message' },
                { key: 'value_at_risk_minor', header: 'Value at risk', align: 'right', render: (e) => inr(e.value_at_risk_minor) },
                { key: 'recommended_action', header: 'Recommended action' },
                { key: 'status', header: 'Status', render: (e) => <span title={e.close_reason ?? undefined}><StatusChip status={e.status} /></span> },
                { key: 'close', header: '', render: (e) => scopes.includes('mrp:plan') && e.status === 'OPEN'
                  ? <Button onClick={() => setClosing(e)}>Close</Button> : null },
              ]}
            />
            {closing && (
              <ReasonDialog title={`Close ${label(closing.code)} exception`} action="Close exception" onClose={() => setClosing(null)}
                hint="Record how the exception was handled (expedited, kept as buffer, settled outside the system). Exceptions of a material also close as superseded when a later run plans it again."
                onSubmit={(reason) => api.post(`/mrp/exceptions/${closing.id}/close`, { reason })} />
            )}
            {summary && (
              <div className="flex gap-2">
                <Button disabled={exceptionOffset === 0} onClick={() => setExceptionOffset(Math.max(0, exceptionOffset - 50))}>Previous</Button>
                <Button disabled={!exceptionsPage.data?.nextOffset} onClick={() => setExceptionOffset(exceptionsPage.data?.nextOffset ?? exceptionOffset)}>Next</Button>
              </div>
            )}
            </div>
          ) },
          { id: 'process', label: 'Process', content: <ProcessPath type="MRP_RUN" objectRef={run.number} /> },
          { id: 'lineage', label: 'Lineage', content: <LineageView type="MRP_RUN" objectRef={run.number} /> },
          { id: 'audit', label: 'Audit', content: <AuditTrail type="MRP_RUN" objectRef={run.number} /> },
        ]} />
      </Card>
    </div>
  );
}

function NettingRow({ r }: { r: NetResult }) {
  const term = (name: string, value: string) => (
    <span className="inline-flex flex-col items-center rounded-md bg-slate-50 px-2 py-1">
      <span className="font-mono text-sm font-semibold tabular-nums text-slate-900">{qty(value)}</span>
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{name}</span>
    </span>
  );
  const op = (s: string) => <span className="px-1 font-mono text-base text-slate-500" aria-hidden>{s}</span>;
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-semibold">{r.material}</span>
        <span className="text-xs text-slate-500">plant {r.plant}</span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${Number(r.net) > 0 ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-800'}`}>
          {Number(r.net) > 0 ? 'Net requirement' : 'Covered by supply'}
        </span>
      </div>
      <p className="sr-only">
        {`${qty(r.gross)} gross minus (${qty(r.on_hand)} on hand plus ${qty(r.open_po)} open PO plus ${qty(r.in_transit)} in transit plus ${qty(r.firm_receipts)} firm receipts plus ${qty(r.open_req ?? '0')} open requisitions) plus ${qty(r.safety_stock)} safety stock equals ${qty(r.net)} net`}
      </p>
      <div className="flex flex-wrap items-center gap-y-2" aria-hidden>
        {term('gross', r.gross)}{op('−')}{op('(')}{term('on hand', r.on_hand)}{op('+')}{term('open PO', r.open_po)}{op('+')}
        {term('in transit', r.in_transit)}{op('+')}{term('firm receipts', r.firm_receipts)}{op('+')}{term('open PRs', r.open_req ?? '0')}{op(')')}{op('+')}{term('safety', r.safety_stock)}{op('=')}
        <span className="inline-flex flex-col items-center rounded-md bg-blue-50 px-2 py-1 ring-1 ring-blue-200">
          <span className="font-mono text-sm font-semibold tabular-nums text-[#1A56DB]">{qty(r.net)}</span>
          <span className="text-[10px] uppercase tracking-wide text-blue-700">net</span>
        </span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Proposals</p>
          {r.proposals.length ? (
            <ul className="mt-1 text-sm text-slate-700">
              {r.proposals.map((p, i) => <li key={i}>{qty(p.qty)} · release {date(p.release_date)} · need {date(p.need_date)}</li>)}
            </ul>
          ) : <p className="mt-1 text-sm text-slate-500">No proposal</p>}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Exceptions</p>
          {r.exceptions.length ? (
            <ul className="mt-1 space-y-1 text-sm">
              {r.exceptions.map((e, i) => (
                <li key={i}><span className="font-medium text-amber-800">{label(e.code)}</span> — {e.message}. <span className="text-slate-600">{e.action}</span></li>
              ))}
            </ul>
          ) : <p className="mt-1 text-sm text-slate-500">None</p>}
        </div>
      </div>
    </div>
  );
}

/** Planned orders of a large run, read as cursor pages (a 50,000-material run has ~120,000). */
function SummaryOrders({ run, canPlan }: { run: Run; canPlan: boolean }) {
  const list = useList<PlannedOrder>(`/mrp/runs/${encodeURIComponent(run.number)}/planned-orders`);
  return (
    <DataTable<PlannedOrder>
      rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
      loadingMore={list.isFetchingNextPage} empty="No planned orders from this run"
      columns={[
        { key: 'number', header: 'Planned order', render: (o) => <span className="font-medium">{o.number}</span> },
        { key: 'material', header: 'Material', render: (o) => o.material ?? '–' },
        { key: 'qty', header: 'Quantity', align: 'right', render: (o) => qty(o.qty) },
        { key: 'release_date', header: 'Release', render: (o) => date(o.release_date) },
        { key: 'need_date', header: 'Need', render: (o) => date(o.need_date) },
        { key: 'source', header: 'Source determination', render: (o) => <SourceSummary source={o.source} /> },
        { key: 'status', header: 'Status', render: (o) => <StatusChip status={o.status} /> },
        { key: 'actions', header: 'Actions', render: (o) => <PlannedOrderActions order={o} canPlan={canPlan} /> },
      ]}
    />
  );
}
