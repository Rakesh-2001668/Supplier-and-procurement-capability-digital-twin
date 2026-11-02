'use client';

import Link from 'next/link';
import { useState } from 'react';
import { DataTable, Kpi, ProblemBox, StatusChip } from '@/components/pic/ui';
import { dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useList } from '@/lib/pic/hooks';
import {
  CheckFilter, ExpiryCell, ExportButton, FilterBar, Flag, MaterialLink, materialHref, Movement, PlantSelect, QueryValue, qs, RefLink, REFERENCE_TYPES, SelectFilter,
  SeverityChip, signedInr, signedQty, StockRow, TextFilter, today, useDebounced, useRules,
} from './_shared';
import { lotHref } from '../receiving/_special';

type Summary = {
  asOf: string; plant: string | null; plants: string[] | null;
  byType: Record<string, { rows: number; qty: string; valueMinor: number }>;
  stockValueMinor: number; stockValueNote: string;
  qualityHold: { openLots: number; ageBucketsDays: Record<string, number>; valueMinor: number };
  blockedValueMinor: number;
  expiring: Record<'expired' | 'within30' | 'within60' | 'within90', { rows: number; valueMinor: number }>;
  belowSafetyCount: number; stockOutCount: number; stockOutDefinition: string; daysOfCover: string | null;
  openReservations: { count: number; openQty: string };
  openCounts: { total: number; byStatus: Record<string, number>; awaitingApproval: number };
  postingsAwaitingApproval: number;
};

// ---------------------------------------------------------------- stock
export function StockTab() {
  const [plant, setPlant] = useState('');
  const [f, setF] = useState({ material: '', sloc: '', stockType: '', batch: '', group: '', below: false, expiring: '' });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const d = useDebounced(f);
  const rules = useRules();
  const summary = useApi<Summary>(`/stock/summary${qs({ plant })}`);
  const list = useList<StockRow>(`/stock${qs({
    plant, material: d.material.trim(), storage_location: d.sloc.trim(), stock_type: d.stockType, batch: d.batch.trim(), material_group: d.group.trim(),
    belowSafety: d.below, expiringWithinDays: d.expiring,
  })}`);
  const s = summary.data;
  const types = rules.data?.enums.stockTypes ?? ['UNRESTRICTED', 'QUALITY', 'BLOCKED', 'CONSIGNMENT', 'SUBCONTRACTOR'];

  return (
    <div className="space-y-6">
      <div className="max-w-xs"><PlantSelect value={plant} onChange={setPlant} /></div>
      {summary.error && <ProblemBox error={summary.error} />}
      {s && (
        <section aria-label="Stock summary" className="space-y-3">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Stock value" value={inr(s.stockValueMinor)} hint={`Own stock at standard price, as of ${s.asOf}`} />
            <Kpi label="Quality hold" value={inr(s.qualityHold.valueMinor)} tone={s.qualityHold.ageBucketsDays['>7'] ? 'warn' : 'default'}
              hint={`${s.qualityHold.openLots} open lots · age 0–2 d: ${s.qualityHold.ageBucketsDays['0-2'] ?? 0}, 3–7 d: ${s.qualityHold.ageBucketsDays['3-7'] ?? 0}, over 7 d: ${s.qualityHold.ageBucketsDays['>7'] ?? 0}`} />
            <Kpi label="Blocked stock" value={inr(s.blockedValueMinor)} tone={s.blockedValueMinor ? 'warn' : 'default'} hint="Blocked stock at standard price" />
            <Kpi label="Days of cover" value={s.daysOfCover ?? '–'} hint="Unrestricted stock over average daily issue" />
            <Kpi label="Below safety stock" value={s.belowSafetyCount} tone={s.belowSafetyCount ? 'warn' : 'good'} hint="Materials with unrestricted stock under safety stock" />
            <Kpi label="Stock-outs" value={s.stockOutCount} tone={s.stockOutCount ? 'bad' : 'good'} hint={s.stockOutDefinition} />
            <Kpi label="Awaiting approval" value={s.postingsAwaitingApproval + s.openCounts.awaitingApproval}
              hint={`${s.postingsAwaitingApproval} stock postings · ${s.openCounts.awaitingApproval} counts`} />
            <Kpi label="Open reservations" value={s.openReservations.count} hint={`${qty(s.openReservations.openQty)} units still reserved · ${s.openCounts.total} counts open`} />
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Expired" value={inr(s.expiring.expired.valueMinor)} tone={s.expiring.expired.rows ? 'bad' : 'good'} hint={`${s.expiring.expired.rows} stock lines past expiry`} />
            <Kpi label="Expiring within 30 days" value={inr(s.expiring.within30.valueMinor)} tone={s.expiring.within30.rows ? 'warn' : 'good'} hint={`${s.expiring.within30.rows} stock lines`} />
            <Kpi label="Expiring in 31–60 days" value={inr(s.expiring.within60.valueMinor)} hint={`${s.expiring.within60.rows} stock lines`} />
            <Kpi label="Expiring in 61–90 days" value={inr(s.expiring.within90.valueMinor)} hint={`${s.expiring.within90.rows} stock lines`} />
          </div>
          <p className="text-xs text-slate-500">{s.stockValueNote}.</p>
        </section>
      )}

      <section aria-label="Stock list">
        <h3 className="mb-2 text-sm font-semibold text-slate-900">Stock by location, type and batch</h3>
        <FilterBar name="Filter stock">
          <TextFilter label="Material or description" value={f.material} onChange={(material) => set({ material })} placeholder="Number prefix or text" />
          <TextFilter label="Storage location" value={f.sloc} onChange={(sloc) => set({ sloc })} />
          <SelectFilter label="Stock type" value={f.stockType} onChange={(stockType) => set({ stockType })}
            options={[{ value: '', label: 'All stock types' }, ...types.map((t) => ({ value: t, label: label(t) }))]} />
          <TextFilter label="Batch" value={f.batch} onChange={(batch) => set({ batch })} />
          <TextFilter label="Material group" value={f.group} onChange={(group) => set({ group })} />
          <SelectFilter label="Expiring within" value={f.expiring} onChange={(expiring) => set({ expiring })}
            options={[{ value: '', label: 'Any expiry' }, { value: '0', label: 'Expired or today' }, { value: '30', label: '30 days' }, { value: '60', label: '60 days' }, { value: '90', label: '90 days' }]} />
          <CheckFilter label="Below safety stock only" checked={f.below} onChange={(below) => set({ below })} />
        </FilterBar>
        <DataTable<StockRow>
          caption="Stock balances" rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
          loadingMore={list.isFetchingNextPage} empty="No stock matches these filters"
          columns={[
            { key: 'material', header: 'Material', render: (r) => <MaterialLink material={r.material} description={r.description} /> },
            { key: 'location', header: 'Plant / location', render: (r) => `${r.plant} / ${r.storageLocation}` },
            { key: 'stockType', header: 'Stock type', render: (r) => <StatusChip status={r.stockType} /> },
            { key: 'batch', header: 'Batch', render: (r) => r.batch ? <Link className="text-[#1A56DB] hover:underline" href={lotHref(r.material, r.batch)} prefetch={false}>{r.batch}</Link> : '–' },
            { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty, r.uom) },
            { key: 'valueMinor', header: 'Value', align: 'right', render: (r) => inr(r.valueMinor) },
            { key: 'expiry', header: 'Expiry', render: (r) => <ExpiryCell expiry={r.expiry} days={r.daysToExpiry} /> },
            { key: 'safety', header: 'Safety stock', align: 'right', render: (r) => (
              <div>
                <p>{Number(r.safetyStock) ? qty(r.safetyStock) : '–'}</p>
                {r.belowSafety && <Flag tone="warn">Below safety stock</Flag>}
              </div>
            ) },
            { key: 'daysOfCover', header: 'Cover (days)', align: 'right', render: (r) => r.daysOfCover ?? '–' },
          ]}
        />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- alerts
type Alert = {
  id: string; type: string; severity: string; title: string; detail: string; material: string | null; description: string | null; plant: string | null;
  storageLocation: string | null; stockType: string | null; batch: string | null; qty: string | null; valueMinor: number | null; since: string | null;
  object: { type: string; ref: string }; suggestedAction: string;
};
type AlertCounts = { countsByType: Record<string, number>; total: number };

function AlertObject({ alert }: { alert: Alert }) {
  const className = 'font-medium text-[#1A56DB] hover:underline';
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {alert.material && <Link prefetch={false} className={className} href={materialHref(alert.material)}>Stock card {alert.material}</Link>}
      {alert.material && alert.batch && <Link prefetch={false} className={className} href={lotHref(alert.material, alert.batch)}>Trace lot {alert.batch}</Link>}
      {alert.object.type === 'INSPECTION_LOT' && <Link prefetch={false} className={className} href="/pic/receiving">Inspection lot {alert.object.ref} (Receiving)</Link>}
    </span>
  );
}

export function AlertsTab() {
  const [plant, setPlant] = useState('');
  const [type, setType] = useState('');
  const rules = useRules();
  // Counts of every type come from the unfiltered answer; the list below is filtered on the server.
  const counts = useApi<AlertCounts>(`/stock/alerts${qs({ plant, limit: 1 })}`);
  const list = useList<Alert>(`/stock/alerts${qs({ plant, type, limit: 100 })}`);
  const alertTypes = rules.data?.enums.alertTypes ?? Object.keys(counts.data?.countsByType ?? {});
  const grouped = list.items.reduce<Record<string, Alert[]>>((acc, a) => ({ ...acc, [a.type]: [...(acc[a.type] ?? []), a] }), {});
  return (
    <div className="space-y-4">
      <div className="max-w-xs"><PlantSelect value={plant} onChange={setPlant} /></div>
      <div role="group" aria-label="Filter alerts by type" className="flex flex-wrap gap-2">
        <button type="button" aria-pressed={type === ''} onClick={() => setType('')}
          className={`rounded-full border px-3 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] ${type === '' ? 'border-[#1A56DB] bg-blue-50 font-semibold text-[#1A56DB]' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'}`}>
          All alerts ({counts.data?.total ?? '…'})
        </button>
        {alertTypes.map((t) => {
          const n = counts.data?.countsByType[t] ?? 0;
          return (
            <button key={t} type="button" aria-pressed={type === t} onClick={() => setType(type === t ? '' : t)}
              className={`rounded-full border px-3 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] ${type === t ? 'border-[#1A56DB] bg-blue-50 font-semibold text-[#1A56DB]' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'} ${n ? '' : 'opacity-60'}`}>
              {label(t)} ({n})
            </button>
          );
        })}
      </div>
      {list.error ? <ProblemBox error={list.error} /> : list.isLoading ? <p className="py-6 text-center text-sm text-slate-500" role="status">Loading alerts…</p> : !list.items.length ? (
        <p className="rounded-lg border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-600">No stock alerts{type ? ` of type ${label(type).toLowerCase()}` : ''}. Nothing needs attention here.</p>
      ) : (
        <div className="space-y-5">
          {Object.entries(grouped).map(([t, alerts]) => (
            <section key={t} aria-label={`${label(t)} alerts`}>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">{label(t)} <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{counts.data?.countsByType[t] ?? alerts.length}</span></h3>
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
                {alerts.map((a) => (
                  <li key={a.id} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[auto_1fr_auto] md:items-start">
                    <div><SeverityChip severity={a.severity} /></div>
                    <div className="min-w-0 space-y-1">
                      <p className="font-medium text-slate-900">{a.title}</p>
                      <p className="text-slate-600">{a.detail}</p>
                      <p className="text-slate-700"><span className="font-medium">Suggested action:</span> {a.suggestedAction}</p>
                      <AlertObject alert={a} />
                    </div>
                    <div className="text-xs text-slate-500 md:text-right">
                      {a.plant && <p>{a.plant}{a.storageLocation ? ` / ${a.storageLocation}` : ''}{a.stockType ? ` · ${label(a.stockType)}` : ''}</p>}
                      {a.valueMinor !== null && <p className="font-medium text-slate-700">{inr(a.valueMinor)}</p>}
                      {a.since && <p>since {a.since.slice(0, 10)}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {list.hasNextPage && <div className="text-center"><button type="button" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50" onClick={() => list.fetchNextPage()}>Load more alerts</button></div>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- movements
export function MovementsTab() {
  const rules = useRules();
  const [plant, setPlant] = useState('');
  const [f, setF] = useState({ material: '', sloc: '', movementType: '', stockType: '', batch: '', referenceType: '', reference: '', from: '', to: '' });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const d = useDebounced(f);
  const filters: Record<string, QueryValue> = {
    plant, material: d.material.trim(), storage_location: d.sloc.trim(), movement_type: d.movementType, stock_type: d.stockType, batch: d.batch.trim(),
    reference_type: d.referenceType, reference: d.reference.trim(), date_from: d.from, date_to: d.to,
  };
  const list = useList<Movement>(`/stock/movements${qs(filters)}`);
  const types = rules.data?.enums.movementTypes ?? {};
  return (
    <div>
      <FilterBar name="Filter movements">
        <TextFilter label="Material or description" value={f.material} onChange={(material) => set({ material })} placeholder="Number prefix or text" />
        <PlantSelect value={plant} onChange={setPlant} />
        <TextFilter label="Storage location" value={f.sloc} onChange={(sloc) => set({ sloc })} />
        <SelectFilter label="Movement type" value={f.movementType} onChange={(movementType) => set({ movementType })}
          options={[{ value: '', label: 'All movement types' }, ...Object.entries(types).map(([code, text]) => ({ value: code, label: `${code} · ${text}` }))]} />
        <SelectFilter label="Stock type" value={f.stockType} onChange={(stockType) => set({ stockType })}
          options={[{ value: '', label: 'All stock types' }, ...(rules.data?.enums.stockTypes ?? []).map((t) => ({ value: t, label: label(t) }))]} />
        <TextFilter label="Batch" value={f.batch} onChange={(batch) => set({ batch })} />
        <SelectFilter label="Document type" value={f.referenceType} onChange={(referenceType) => set({ referenceType })}
          options={[{ value: '', label: 'All documents' }, ...REFERENCE_TYPES.map((t) => ({ value: t, label: label(t) }))]} />
        <TextFilter label="Document number" value={f.reference} onChange={(reference) => set({ reference })} placeholder="e.g. STP-1001" />
        <TextFilter label="Posted from" type="date" value={f.from} onChange={(from) => set({ from })} />
        <TextFilter label="Posted to" type="date" value={f.to} onChange={(to) => set({ to })} />
      </FilterBar>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">Newest first. Quantities are signed: + adds to stock, − takes from it. Values are as at posting.</p>
        <ExportButton path={`/stock/movements/export${qs(filters)}`} fileName={`stock_movements_${today()}.csv`}>Export CSV</ExportButton>
      </div>
      <DataTable<Movement>
        caption="Stock movement ledger" rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} empty="No movements match these filters"
        columns={[
          { key: 'createdAt', header: 'Posted', render: (m) => <span className="whitespace-nowrap">{dateTime(m.createdAt)}</span> },
          { key: 'material', header: 'Material', render: (m) => <MaterialLink material={m.material} description={m.description} /> },
          { key: 'location', header: 'Plant / location', render: (m) => (
            <div><p>{m.plant} / {m.storageLocation}</p><p className="text-xs text-slate-500">{label(m.stockType)}{m.batch ? ` · lot ${m.batch}` : ''}</p></div>
          ) },
          { key: 'movementType', header: 'Movement', render: (m) => <div><span className="font-mono text-xs">{m.movementType}</span><p className="text-xs text-slate-500">{m.movementText}</p></div> },
          { key: 'qty', header: 'Quantity', align: 'right', render: (m) => <span className={Number(m.qty) < 0 ? 'font-semibold text-red-700' : 'font-semibold text-emerald-700'}>{signedQty(m.qty, m.uom)}</span> },
          { key: 'valueMinor', header: 'Value', align: 'right', render: (m) => signedInr(m.valueMinor) },
          { key: 'reference', header: 'Document', render: (m) => <RefLink type={m.reference.type} docRef={m.reference.ref} /> },
          { key: 'reason', header: 'Reason', render: (m) => m.reasonCode ?? '–' },
          { key: 'actor', header: 'Posted by', render: (m) => m.actor?.name ?? 'System' },
        ]}
      />
    </div>
  );
}
