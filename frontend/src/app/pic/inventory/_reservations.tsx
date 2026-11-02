'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Field, Input, Select, StatusChip } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, label, qty } from '@/lib/pic/format';
import { useCommand, useList } from '@/lib/pic/hooks';
import { useSessionUser } from '../invoices/_components';
import { StockHint } from './_postings';
import {
  CheckFilter, FilterBar, Flag, isQty, MaterialInput, PlantSelect, qs, reservationHref, SelectFilter, SlocInput, TextFilter, today, UserRef, useDebounced, usePlants,
  useReference, useRules, ReasonDialog,
} from './_shared';

export type Reservation = {
  id: string; number: string; status: string; companyCode: string; material: string; description: string; uom: string; plant: string; storageLocation: string;
  qty: string; issuedQty: string; openQty: string; needDate: string; costObject: string | null; purpose: string | null; requester: UserRef;
  availabilityAtCreation: { onHand: string; reservedByOthers: string; available: string; shortBy: string; checkedAt: string } | null;
  availableNow: string | null; demandElement: string | null; rule: string | null; closedAt: string | null; closedReason: string | null;
  issues: { at: string; batch: string; qty: string; valueMinor: number | null }[]; createdAt: string | null; rowVersion: number;
};

export const OPEN_RESERVATION = ['OPEN', 'PARTIALLY_ISSUED'];
const RESERVATION_STATUS_FALLBACK = ['OPEN', 'PARTIALLY_ISSUED', 'ISSUED', 'CANCELLED', 'EXPIRED'];

export function ShortFlag({ r }: { r: Reservation }) {
  const short = Number(r.availabilityAtCreation?.shortBy ?? 0);
  return short > 0 ? <Flag tone="warn">Short by {qty(short, r.uom)} when reserved</Flag> : null;
}

// ---------------------------------------------------------------- list
export function ReservationsTab({ canPost }: { canPost: boolean }) {
  const rules = useRules();
  const [plant, setPlant] = useState('');
  const [f, setF] = useState({ status: '', material: '', mine: false });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const d = useDebounced(f);
  const [creating, setCreating] = useState(false);
  const list = useList<Reservation>(`/reservations${qs({ plant, status: d.status, material: d.material.trim(), mine: d.mine })}`);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-3xl text-sm text-slate-600">
          A reservation sets stock aside for a cost object and is demand for MRP until it is issued or cancelled. An unavailable quantity is a warning (it still
          becomes demand) unless the reservation rule blocks it.
        </p>
        {canPost && <Button variant="primary" onClick={() => setCreating(true)}>New reservation</Button>}
      </div>
      <FilterBar name="Filter reservations">
        <SelectFilter label="Status" value={f.status} onChange={(status) => set({ status })}
          options={[{ value: '', label: 'All statuses' }, ...(rules.data?.enums.reservationStatuses ?? RESERVATION_STATUS_FALLBACK).map((s) => ({ value: s, label: label(s) }))]} />
        <TextFilter label="Material number" value={f.material} onChange={(material) => set({ material })} />
        <PlantSelect value={plant} onChange={setPlant} />
        <CheckFilter label="Requested by me" checked={f.mine} onChange={(mine) => set({ mine })} />
      </FilterBar>
      <DataTable<Reservation>
        caption="Stock reservations" rows={list.items} loading={list.isLoading} error={list.error} hasMore={list.hasNextPage} onLoadMore={() => list.fetchNextPage()}
        loadingMore={list.isFetchingNextPage} rowHref={(r) => reservationHref(r.number)} empty="No reservations match these filters"
        columns={[
          { key: 'number', header: 'Reservation' },
          { key: 'material', header: 'Material', render: (r) => <div><p className="font-medium">{r.material}</p><p className="max-w-[16rem] truncate text-xs text-slate-500" title={r.description}>{r.description}</p></div> },
          { key: 'location', header: 'Plant / location', render: (r) => `${r.plant} / ${r.storageLocation}` },
          { key: 'status', header: 'Status', render: (r) => <div className="space-y-1"><StatusChip status={r.status} /><div><ShortFlag r={r} /></div></div> },
          { key: 'qty', header: 'Reserved', align: 'right', render: (r) => qty(r.qty, r.uom) },
          { key: 'issuedQty', header: 'Issued', align: 'right', render: (r) => qty(r.issuedQty) },
          { key: 'openQty', header: 'Open', align: 'right', render: (r) => qty(r.openQty) },
          { key: 'needDate', header: 'Needed', render: (r) => {
            const late = OPEN_RESERVATION.includes(r.status) && r.needDate < today();
            return <span className={late ? 'font-medium text-amber-700' : ''}>{date(r.needDate)}{late ? ' (overdue)' : ''}</span>;
          } },
          { key: 'costObject', header: 'Cost object', render: (r) => r.costObject ?? '–' },
          { key: 'requester', header: 'Requested by', render: (r) => r.requester?.name ?? '–' },
          { key: 'action', header: '', render: (r) => <ReservationActions reservation={r} /> },
        ]}
      />
      {creating && <CreateReservationDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------- create
export function CreateReservationDialog({ onClose }: { onClose: () => void }) {
  const rules = useRules();
  const reference = useReference();
  const { plants } = usePlants();
  const [material, setMaterial] = useState('');
  const [plantChoice, setPlant] = useState('');
  const plant = plantChoice || plants[0]?.code || '';
  const [sloc, setSloc] = useState('');
  const [quantity, setQuantity] = useState('');
  const [need, setNeed] = useState('');
  const [costObject, setCostObject] = useState('');
  const [purpose, setPurpose] = useState('');
  const [result, setResult] = useState<Reservation | null>(null);
  const body = rules.data?.reservation.body;
  const costRequired = body?.requireCostObject ?? true;
  const problem = !material.trim() ? 'Choose the material' : !plant ? 'Choose the plant' : !sloc.trim() ? 'Enter the storage location' : !isQty(quantity) ? 'The quantity must be positive'
    : !need ? 'Enter the date the stock is needed' : need < today() ? 'The need date cannot be in the past'
      : costRequired && !costObject.trim() ? 'A reservation names the cost object it is for, e.g. COST_CENTER:6100'
        : costObject.trim() && !/^[A-Z_]+:[A-Za-z0-9._-]+$/.test(costObject.trim()) ? 'The cost object looks like COST_CENTER:6100' : null;
  const create = useCommand(() => api.post<Reservation>('/reservations', {
    material: material.trim(), plant, storageLocation: sloc.trim(), qty: quantity.trim(), needDate: need, costObject: costObject.trim() || undefined, purpose: purpose || undefined,
  }), { success: (r) => `${r.number} reserved`, onSuccess: setResult });

  return (
    <Dialog open title={result ? `${result.number} created` : 'New reservation'} onClose={onClose}>
      {result ? (
        <div className="space-y-3">
          <p className="text-sm">
            <span className="font-semibold">{qty(result.qty, result.uom)} {result.material}</span> reserved at {result.plant}/{result.storageLocation} for {result.costObject ?? 'no cost object'},
            needed {date(result.needDate)}.
          </p>
          {Number(result.availabilityAtCreation?.shortBy ?? 0) > 0 ? (
            <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <p className="font-semibold">Warning: not fully available</p>
              <p>{Number(result.availabilityAtCreation?.available) > 0 ? `Only ${qty(result.availabilityAtCreation?.available, result.uom)} is free` : 'Nothing is free'} ({qty(result.availabilityAtCreation?.onHand)} on hand, {qty(result.availabilityAtCreation?.reservedByOthers)} reserved by others):
                short by {qty(result.availabilityAtCreation?.shortBy, result.uom)}. The reservation still stands and is demand for MRP, which will plan the shortfall.</p>
            </div>
          ) : (
            <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">Fully covered: {qty(result.availabilityAtCreation?.available, result.uom)} was free when you reserved.</p>
          )}
          <div className="flex justify-end"><Button variant="primary" onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="md:col-span-2"><MaterialInput value={material} onChange={setMaterial} required /></div>
            <Field label="Plant" required>{(id) => <Select id={id} value={plant} onChange={(e) => setPlant(e.target.value)} options={plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))} />}</Field>
            <SlocInput plant={plant} value={sloc} onChange={setSloc} required />
            <Field label="Quantity" required>{(id) => <Input id={id} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}</Field>
            <Field label="Need date" required hint={body ? `At most ${body.maxOpenDays} days ahead` : undefined}>
              {(id, by) => <Input id={id} aria-describedby={by} type="date" min={today()} value={need} onChange={(e) => setNeed(e.target.value)} />}
            </Field>
            <Field label="Cost object" required={costRequired} hint="TYPE:CODE, e.g. COST_CENTER:6100">
              {(id, by) => <>
                <Input id={id} aria-describedby={by} list={`${id}-cost`} value={costObject} autoComplete="off" onChange={(e) => setCostObject(e.target.value.toUpperCase())} />
                <datalist id={`${id}-cost`}>{(reference.data?.costObjects ?? []).map((c) => <option key={`${c.type}:${c.code}`} value={`${c.type}:${c.code}`}>{c.name}</option>)}</datalist>
              </>}
            </Field>
            <Field label="Purpose">
              {(id) => <Select id={id} value={purpose} onChange={(e) => setPurpose(e.target.value)} options={[{ value: '', label: 'Not stated' }, ...(body?.purposes ?? []).map((p) => ({ value: p, label: label(p) }))]} />}
            </Field>
          </div>
          <div className="mt-2"><StockHint material={material} plant={plant} type="RESERVE" /></div>
          {problem && <p className="mt-2 text-xs text-amber-700" role="status">{problem}</p>}
          <p className="mt-2 text-xs text-slate-500">{body?.blockWhenUnavailable ? 'This tenant refuses a reservation for more than is available.' : 'If less is available you get a warning, and the reservation still becomes demand for MRP.'}</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!!problem} busy={create.isPending} onClick={() => create.mutate()}>Reserve</Button>
          </div>
        </>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------- issue and cancel
function IssueDialog({ reservation, onClose }: { reservation: Reservation; onClose: () => void }) {
  const [quantity, setQuantity] = useState('');
  const [batch, setBatch] = useState('');
  const invalid = quantity.trim() !== '' && (!isQty(quantity) || Number(quantity) > Number(reservation.openQty));
  const issue = useCommand(() => api.post<Reservation>(`/reservations/${encodeURIComponent(reservation.number)}/issue`, {
    qty: quantity.trim() || undefined, batch: batch.trim() || undefined,
  }), { success: (r) => `${r.number} ${label(r.status).toLowerCase()}: ${qty(r.issuedQty, r.uom)} issued to ${r.costObject ?? 'the cost object'}`, onSuccess: onClose });
  return (
    <Dialog open title={`Issue ${reservation.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        Goods issue (movement 201) of {reservation.material} from {reservation.plant}/{reservation.storageLocation} to {reservation.costObject ?? 'the cost object'}.
        {' '}Open: <span className="font-semibold">{qty(reservation.openQty, reservation.uom)}</span>
        {reservation.availableNow !== null && <> · free to issue now: <span className="font-semibold">{qty(reservation.availableNow, reservation.uom)}</span></>}.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Field label="Quantity to issue" hint={`Empty: everything still reserved (${qty(reservation.openQty)})`} error={invalid ? `Between 0 and ${qty(reservation.openQty)}` : undefined}>
          {(id, by) => <Input id={id} aria-describedby={by} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}
        </Field>
        <Field label="Lot / batch" hint="Empty: first expiry first out">{(id, by) => <Input id={id} aria-describedby={by} value={batch} onChange={(e) => setBatch(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Back</Button>
        <Button variant="primary" disabled={invalid} busy={issue.isPending} onClick={() => issue.mutate()}>Issue goods</Button>
      </div>
    </Dialog>
  );
}

export function ReservationActions({ reservation }: { reservation: Reservation }) {
  const user = useSessionUser();
  const rules = useRules();
  const [dialog, setDialog] = useState<'issue' | 'cancel' | null>(null);
  const cancel = useCommand((reason: string) => api.post<Reservation>(`/reservations/${encodeURIComponent(reservation.number)}/cancel`, { reason }),
    { success: (r) => `${r.number} cancelled; the demand for MRP is released`, onSuccess: () => setDialog(null) });
  if (!rules.data || !OPEN_RESERVATION.includes(reservation.status)) return null;
  const canPost = rules.data.me.canPost;
  const canCancel = canPost || (!!user && reservation.requester?.id === user.id);
  return (
    <div className="flex flex-wrap gap-2">
      {canPost && <Button variant="primary" aria-label={`Issue ${reservation.number}`} onClick={() => setDialog('issue')}>Issue</Button>}
      {canCancel && <Button variant="danger" aria-label={`Cancel ${reservation.number}`} onClick={() => setDialog('cancel')}>Cancel</Button>}
      {dialog === 'issue' && <IssueDialog reservation={reservation} onClose={() => setDialog(null)} />}
      {dialog === 'cancel' && <ReasonDialog title={`Cancel ${reservation.number}`} fieldLabel="Reason for cancelling" required confirm="Cancel reservation" variant="danger" busy={cancel.isPending}
        intro={<>The open {qty(reservation.openQty, reservation.uom)} of {reservation.material} is released and stops being demand for MRP. {reservation.issuedQty !== '0' && Number(reservation.issuedQty) > 0 ? `${qty(reservation.issuedQty)} already issued stays issued.` : ''}</>}
        onConfirm={(t) => cancel.mutate(t)} onClose={() => setDialog(null)} />}
    </div>
  );
}

