'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ObjectPage } from '@/components/pic/object';
import { DataTable, Facts } from '@/components/pic/ui';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { Reservation, ReservationActions, ShortFlag } from '../../_reservations';
import { materialHref } from '../../_shared';

export default function ReservationPage() {
  const { ref } = useParams<{ ref: string }>();
  const number = decodeURIComponent(ref);
  const { data: r, isLoading, error } = useApi<Reservation>(`/reservations/${encodeURIComponent(number)}`);
  const a = r?.availabilityAtCreation;
  return (
    <ObjectPage
      type="STOCK_RESERVATION" docRef={r?.number ?? ''} eyebrow="STK-05 · Reservation" loading={isLoading} error={error}
      title={<>{r?.number} <span className="text-base font-normal text-slate-500">{r?.description}</span></>}
      status={r?.status}
      actions={r && <ReservationActions reservation={r} />}
      facts={r && (
        <div className="space-y-3">
          <Facts items={[
            ['Material', <Link key="m" className="text-[#1A56DB] hover:underline" href={materialHref(r.material)}>{r.material}</Link>], ['Location', `${r.plant} / ${r.storageLocation}`],
            ['Reserved', qty(r.qty, r.uom)], ['Issued', qty(r.issuedQty, r.uom)], ['Open', qty(r.openQty, r.uom)], ['Needed by', date(r.needDate)],
            ['Cost object', r.costObject ?? '–'], ['Purpose', r.purpose ? label(r.purpose) : '–'], ['Requested by', r.requester?.name ?? '–'],
            ['Free to issue now', r.availableNow !== null ? qty(r.availableNow, r.uom) : '–'], ['Rule', r.rule ?? '–'],
            ...(r.closedAt ? [['Closed', `${dateTime(r.closedAt)} · ${r.closedReason ?? ''}`] as [string, string]] : []),
          ]} />
          {a && (
            <p className="text-sm text-slate-700">
              When reserved: {qty(a.onHand, r.uom)} on hand, {qty(a.reservedByOthers)} reserved by others, {qty(Math.max(0, Number(a.available)), r.uom)} free. <ShortFlag r={r} />
            </p>
          )}
        </div>
      )}
      lines={r && (
        <DataTable<Reservation['issues'][number] & { id: string }>
          caption="Goods issues" rows={r.issues.map((x, i) => ({ ...x, id: String(i) }))} empty="Nothing issued yet"
          columns={[
            { key: 'at', header: 'Issued', render: (x) => dateTime(x.at) },
            { key: 'batch', header: 'Lot', render: (x) => x.batch || '–' },
            { key: 'qty', header: 'Quantity', align: 'right', render: (x) => qty(x.qty, r.uom) },
            { key: 'valueMinor', header: 'Value', align: 'right', render: (x) => inr(x.valueMinor) },
          ]}
        />
      )}
    />
  );
}
