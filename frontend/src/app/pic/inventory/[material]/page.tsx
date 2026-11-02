'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useState } from 'react';
import { Card, DataTable, Empty, Facts, Kpi, LinkButton, Loading, ProblemBox, Select, StatusChip, Tabs } from '@/components/pic/ui';
import { date, inr, label, qty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { lotHref } from '../../receiving/_special';
import { ExpiryCell, Flag, Movement, qs, RefLink, reservationHref, signedInr, signedQty, StockRow } from '../_shared';

type Bucket = { from: string; to: string; receipts: string; requirements: string; opening: string; projected: string; belowSafety: boolean; shortage: boolean };
type Profile = {
  material: string; plant: string; mrpType: string; bucket: string; asOf: string; horizonTo: string; onHand: string; openPo: string; inTransit: string;
  firmPlannedReceipts: string; demand: string; safetyStock: string; available: string; reorderPoint: string | null; maxStock: string | null; reserved: string;
  availableToPromise: string; receipts: { date: string; qty: string; kind: string; ref: string }[];
  requirements: { date: string; qty: string; type: string; reference: string }[]; buckets: Bucket[];
};
type CardReservation = { number: string; status: string; plant: string; storageLocation: string; qty: string; openQty: string; needDate: string; costObject: string | null; purpose: string | null };
type StockCard = {
  material: { number: string; description: string; uom: string; type: string; materialGroup: string | null; mrpType: string | null; status: string; batchManaged: boolean; expiryManaged: boolean };
  stock: StockRow[]; byType: Record<string, { qty: string; valueMinor: number }>; requirements: Profile[]; reservations: CardReservation[]; movements: Movement[];
  valuation: { method: string; standardPriceMinor: number | null; valuationClass: string | null; ownStockQty: string; ownStockValueMinor: number | null; blockedValueMinor: number };
};

const HORIZONS = [30, 60, 90, 180, 365];

export default function StockCardPage() {
  const { material: param } = useParams<{ material: string }>();
  const material = decodeURIComponent(param);
  const { data, isLoading, error } = useApi<StockCard>(`/stock/materials/${encodeURIComponent(material)}`);
  if (error && !data) return <div className="space-y-4"><ProblemBox error={error} /><LinkButton href="/pic/inventory">Back to inventory</LinkButton></div>;
  if (isLoading || !data) return <Loading text="Loading stock card…" />;
  const m = data.material;
  const v = data.valuation;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs uppercase tracking-wider text-slate-500">INV-02 · Stock card</p>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-[#0B1020]">{m.number} <span className="text-lg font-normal text-slate-600">{m.description}</span></h1>
            <StatusChip status={m.status} />
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <LinkButton href="/pic/inventory">All inventory</LinkButton>
        </div>
      </div>

      <Card>
        <Facts items={[
          ['Unit of measure', m.uom], ['Material type', label(m.type)], ['Material group', m.materialGroup ?? '–'], ['MRP type', m.mrpType ?? '–'],
          ['Lot managed', m.batchManaged ? 'Yes' : 'No'], ['Expiry managed', m.expiryManaged ? 'Yes' : 'No'],
          ['Own stock', qty(v.ownStockQty, m.uom)], ['Own stock value', inr(v.ownStockValueMinor)],
        ]} />
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
          {['UNRESTRICTED', 'QUALITY', 'BLOCKED', 'CONSIGNMENT', 'SUBCONTRACTOR'].map((t) => (
            <Kpi key={t} label={label(t)} value={qty(data.byType[t]?.qty ?? 0, m.uom)} hint={data.byType[t] ? inr(data.byType[t].valueMinor) : 'No stock'} />
          ))}
        </div>
      </Card>

      <Card>
        <Tabs label="Stock card sections" tabs={[
          { id: 'stock', label: 'Stock', content: <StockLines card={data} /> },
          { id: 'requirements', label: 'Requirements profile', content: <Requirements material={m.number} uom={m.uom} /> },
          { id: 'reservations', label: `Reservations (${data.reservations.length})`, content: <Reservations rows={data.reservations} uom={m.uom} /> },
          { id: 'movements', label: 'Recent movements', content: <Movements rows={data.movements} material={m.number} /> },
          { id: 'valuation', label: 'Valuation', content: (
            <Facts items={[['Method', label(v.method)], ['Standard price', inr(v.standardPriceMinor)], ['Valuation class', v.valuationClass ?? '–'],
              ['Own stock value', inr(v.ownStockValueMinor)], ['Blocked stock value', inr(v.blockedValueMinor)]]} />
          ) },
        ]} />
      </Card>
    </div>
  );
}

function StockLines({ card }: { card: StockCard }) {
  return (
    <DataTable<StockRow>
      caption={`Stock of ${card.material.number}`} rows={card.stock} empty="No stock of this material at your plants"
      columns={[
        { key: 'location', header: 'Plant / location', render: (r) => `${r.plant} / ${r.storageLocation}` },
        { key: 'stockType', header: 'Stock type', render: (r) => <StatusChip status={r.stockType} /> },
        { key: 'batch', header: 'Lot', render: (r) => r.batch ? <Link className="text-[#1A56DB] hover:underline" href={lotHref(r.material, r.batch)} prefetch={false}>{r.batch}</Link> : '–' },
        { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty, r.uom) },
        { key: 'valueMinor', header: 'Value', align: 'right', render: (r) => inr(r.valueMinor) },
        { key: 'expiry', header: 'Expiry', render: (r) => <ExpiryCell expiry={r.expiry} days={r.daysToExpiry} /> },
        { key: 'safety', header: 'Safety stock', align: 'right', render: (r) => <div><p>{Number(r.safetyStock) ? qty(r.safetyStock) : '–'}</p>{r.belowSafety && <Flag tone="warn">Below safety stock</Flag>}</div> },
        { key: 'cover', header: 'Cover (days)', align: 'right', render: (r) => r.daysOfCover ?? '–' },
      ]}
    />
  );
}

function Requirements({ material, uom }: { material: string; uom: string }) {
  const [horizon, setHorizon] = useState(90);
  const { data: card, isLoading, error } = useApi<StockCard>(`/stock/materials/${encodeURIComponent(material)}${qs({ horizonDays: horizon })}`);
  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          The stock/requirements list MRP nets: unrestricted stock, open purchase orders, shipments in transit, firm planned receipts and demand including reservations,
          with the projected balance per planning bucket.
        </p>
        <label className="flex items-center gap-2 text-xs font-medium text-slate-700">
          Horizon
          <Select value={String(horizon)} onChange={(e) => setHorizon(Number(e.target.value))} options={HORIZONS.map((h) => ({ value: String(h), label: `${h} days` }))} className="w-auto" />
        </label>
      </div>
      {error && <ProblemBox error={error} />}
      {isLoading && <Loading text="Loading the requirements profile…" />}
      {card && !card.requirements.length && <Empty title="No planning data for this material" hint="It has no stock, demand or planning parameters at your plants." />}
      {(card?.requirements ?? []).map((p) => (
        <section key={p.plant} aria-label={`Requirements at plant ${p.plant}`} className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Plant {p.plant} <span className="font-normal text-slate-500">· {p.mrpType ?? 'no MRP type'} · {label(p.bucket)} buckets · as of {date(p.asOf)} to {date(p.horizonTo)}</span></h3>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
            <Kpi label="On hand (unrestricted)" value={qty(p.onHand, uom)} />
            <Kpi label="Open purchase orders" value={qty(p.openPo, uom)} />
            <Kpi label="In transit" value={qty(p.inTransit, uom)} />
            <Kpi label="Firm planned receipts" value={qty(p.firmPlannedReceipts, uom)} />
            <Kpi label="Demand" value={qty(p.demand, uom)} hint="Orders, requisitions and reservations" />
            <Kpi label="Safety stock" value={qty(p.safetyStock, uom)} />
            <Kpi label="Reorder point" value={p.reorderPoint ? qty(p.reorderPoint, uom) : '–'} />
            <Kpi label="Reserved" value={qty(p.reserved, uom)} />
            <Kpi label="Available (with supply)" value={qty(p.available, uom)} hint="On hand + PO + in transit + firm planned" />
            <Kpi label="Available to promise" value={qty(p.availableToPromise, uom)} tone={Number(p.availableToPromise) < 0 ? 'bad' : 'default'} hint="On hand minus reserved" />
          </div>
          <DataTable<Bucket & { id: string }>
            caption={`Projected balance at ${p.plant}`} rows={p.buckets.map((b) => ({ ...b, id: b.from }))} empty="No receipts or requirements inside the horizon"
            columns={[
              { key: 'from', header: 'Bucket', render: (b) => (b.from === b.to ? date(b.from) : `${date(b.from)} – ${date(b.to)}`) },
              { key: 'opening', header: 'Opening', align: 'right', render: (b) => qty(b.opening) },
              { key: 'receipts', header: 'Receipts', align: 'right', render: (b) => Number(b.receipts) ? signedQty(b.receipts) : '–' },
              { key: 'requirements', header: 'Requirements', align: 'right', render: (b) => Number(b.requirements) ? signedQty(-Number(b.requirements)) : '–' },
              { key: 'projected', header: 'Projected balance', align: 'right', render: (b) => (
                <span className={b.shortage ? 'font-semibold text-red-700' : b.belowSafety ? 'font-semibold text-amber-700' : ''}>{qty(b.projected, uom)}</span>
              ) },
              { key: 'flag', header: 'Status', render: (b) => b.shortage ? <Flag tone="bad">Shortage</Flag> : b.belowSafety ? <Flag tone="warn">Below safety stock</Flag> : <Flag tone="good">Covered</Flag> },
            ]}
          />
          <details className="rounded-lg border border-slate-200 px-4 py-2 text-sm">
            <summary className="cursor-pointer font-medium text-slate-800">Receipts and requirements behind the buckets ({p.receipts.length} supply, {p.requirements.length} demand)</summary>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <DataTable<{ id: string; date: string; qty: string; kind: string; ref: string }> caption="Supply elements" rows={p.receipts.map((r, i) => ({ ...r, id: `${r.ref}-${i}` }))} empty="No supply"
                columns={[{ key: 'date', header: 'Date', render: (r) => date(r.date) }, { key: 'kind', header: 'Kind', render: (r) => label(r.kind) }, { key: 'ref', header: 'Reference' },
                  { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty, uom) }]} />
              <DataTable<{ id: string; date: string; qty: string; type: string; reference: string }> caption="Demand elements" rows={p.requirements.map((r, i) => ({ ...r, id: `${r.reference}-${i}` }))} empty="No demand"
                columns={[{ key: 'date', header: 'Date', render: (r) => date(r.date) }, { key: 'type', header: 'Type', render: (r) => label(r.type) }, { key: 'reference', header: 'Reference' },
                  { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty, uom) }]} />
            </div>
          </details>
        </section>
      ))}
    </div>
  );
}

function Reservations({ rows, uom }: { rows: CardReservation[]; uom: string }) {
  return (
    <DataTable<CardReservation & { id: string }>
      caption="Open reservations" rows={rows.map((r) => ({ ...r, id: r.number }))} empty="No open reservations for this material" rowHref={(r) => reservationHref(r.number)}
      columns={[
        { key: 'number', header: 'Reservation' },
        { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
        { key: 'location', header: 'Plant / location', render: (r) => `${r.plant} / ${r.storageLocation}` },
        { key: 'qty', header: 'Reserved', align: 'right', render: (r) => qty(r.qty, uom) },
        { key: 'openQty', header: 'Open', align: 'right', render: (r) => qty(r.openQty, uom) },
        { key: 'needDate', header: 'Needed', render: (r) => date(r.needDate) },
        { key: 'costObject', header: 'Cost object', render: (r) => r.costObject ?? '–' },
        { key: 'purpose', header: 'Purpose', render: (r) => r.purpose ? label(r.purpose) : '–' },
      ]}
    />
  );
}

function Movements({ rows, material }: { rows: Movement[]; material: string }) {
  return (
    <div className="space-y-3">
      <DataTable<Movement>
        caption={`Recent movements of ${material}`} rows={rows} empty="No movements yet"
        columns={[
          { key: 'createdAt', header: 'Posted', render: (m) => <span className="whitespace-nowrap">{date(m.createdAt)}</span> },
          { key: 'location', header: 'Plant / location', render: (m) => <div><p>{m.plant} / {m.storageLocation}</p><p className="text-xs text-slate-500">{label(m.stockType)}{m.batch ? ` · lot ${m.batch}` : ''}</p></div> },
          { key: 'movementType', header: 'Movement', render: (m) => <div><span className="font-mono text-xs">{m.movementType}</span><p className="text-xs text-slate-500">{m.movementText}</p></div> },
          { key: 'qty', header: 'Quantity', align: 'right', render: (m) => <span className={Number(m.qty) < 0 ? 'font-semibold text-red-700' : 'font-semibold text-emerald-700'}>{signedQty(m.qty, m.uom)}</span> },
          { key: 'valueMinor', header: 'Value', align: 'right', render: (m) => signedInr(m.valueMinor) },
          { key: 'reference', header: 'Document', render: (m) => <RefLink type={m.reference.type} docRef={m.reference.ref} /> },
          { key: 'actor', header: 'Posted by', render: (m) => m.actor?.name ?? 'System' },
        ]}
      />
      <Link href={`/pic/inventory`} className="text-sm text-[#1A56DB] hover:underline">Full ledger with filters and export: Inventory, Movements tab</Link>
    </div>
  );
}
