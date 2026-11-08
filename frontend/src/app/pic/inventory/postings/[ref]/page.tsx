'use client';

import { useParams } from 'next/navigation';
import { ObjectPage } from '@/components/pic/object';
import { DataTable, Facts } from '@/components/pic/ui';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { PostingActions, PostingDetail, PostingLine } from '../../_postings';
import { Flag, MaterialLink, signedInr, signedQty } from '../../_shared';

const where = (plant: string | null, sloc: string | null, type: string | null) => (plant ? `${plant} / ${sloc}${type ? ` · ${label(type)}` : ''}` : '–');

export default function PostingPage() {
  const { ref } = useParams<{ ref: string }>();
  const number = decodeURIComponent(ref);
  const { data: p, isLoading, error } = useApi<PostingDetail>(`/stock-postings/${encodeURIComponent(number)}`);
  const person = (u: PostingDetail['createdBy'], at?: string | null) => (u ? `${u.name}${at ? ` · ${dateTime(at)}` : ''}` : '–');
  return (
    <ObjectPage
      type="STOCK_POSTING" docRef={p?.number ?? ''} eyebrow="STK-03 · Stock posting" loading={isLoading} error={error}
      title={<>{p?.number} <span className="text-base font-normal text-slate-500">{p ? label(p.type) : ''} at {p?.plant}</span></>}
      status={p?.status}
      actions={p && <PostingActions posting={p} />}
      facts={p && (
        <div className="space-y-3">
          {p.warnings.length > 0 && (
            <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              {p.warnings.map((w) => <p key={`${w.code}-${w.line}`}><span className="font-semibold">Line {w.line} {w.material}:</span> {w.detail}</p>)}
            </div>
          )}
          <Facts items={[
            ['Type', label(p.type)], ['Plant', `${p.plant} (${p.companyCode})`], ['Posting date', date(p.postingDate)], ['Value', inr(p.totalValueMinor)],
            ['Reason code', p.reasonCode ?? '–'], ['Reason', p.reason ?? '–'], ['Rule', p.rule ?? '–'], ['ERP document', p.erpDocument ?? '–'],
            ['Raised by', person(p.createdBy, p.createdAt)], ['Submitted by', person(p.submittedBy, p.submittedAt)],
            ['Approved by', p.autoPosted ? 'Rule (auto-post limit)' : person(p.approvedBy, p.approvedAt)],
            ['Posted by', p.autoPosted ? 'Posted automatically' : person(p.postedBy, p.postedAt)],
            ...(p.decisionComment ? [['Decision comment', p.decisionComment] as [string, string]] : []),
          ]} />
          {p.autoPosted && <Flag tone="muted">Below the auto-post limit: no approver needed</Flag>}
        </div>
      )}
      lines={p && (
        <DataTable<PostingLine & { id: string }>
          caption="Posting lines" rows={p.lines.map((l) => ({ ...l, id: String(l.lineNo) }))}
          columns={[
            { key: 'lineNo', header: 'Line' },
            { key: 'material', header: 'Material', render: (l) => <MaterialLink material={l.material} description={l.description} /> },
            { key: 'batch', header: 'Lot', render: (l) => l.batch || '–' },
            { key: 'qty', header: 'Quantity', align: 'right', render: (l) => qty(l.qty, l.uom) },
            { key: 'from', header: 'From', render: (l) => where(l.fromPlant, l.fromStorageLocation, l.fromStockType) },
            { key: 'to', header: 'To', render: (l) => where(l.toPlant, l.toStorageLocation, l.toStockType) },
            { key: 'movementType', header: 'Movement', render: (l) => <span className="font-mono text-xs">{l.movementType}</span> },
            { key: 'unitPriceMinor', header: 'Standard price', align: 'right', render: (l) => inr(l.unitPriceMinor) },
            { key: 'valueMinor', header: 'Value', align: 'right', render: (l) => inr(l.valueMinor) },
          ]}
        />
      )}
      extraTabs={p ? [{
        id: 'movements', label: `Stock movements (${p.movements.length})`, content: (
          <DataTable<PostingDetail['movements'][number] & { id: string }>
            caption="Movements posted" rows={p.movements.map((m, i) => ({ ...m, id: String(i) }))}
            empty={p.status === 'POSTED' ? 'No movements' : 'Nothing is posted to stock until the posting is approved and posted'}
            columns={[
              { key: 'material', header: 'Material', render: (m) => (m.material ? <MaterialLink material={m.material} /> : '–') },
              { key: 'movementType', header: 'Movement', render: (m) => <span className="font-mono text-xs">{m.movementType}</span> },
              { key: 'location', header: 'Plant / location', render: (m) => where(m.plant, m.storageLocation, m.stockType) },
              { key: 'batch', header: 'Lot', render: (m) => m.batch || '–' },
              { key: 'qty', header: 'Quantity', align: 'right', render: (m) => signedQty(m.qty) },
              { key: 'valueMinor', header: 'Value', align: 'right', render: (m) => signedInr(m.valueMinor) },
            ]}
          />
        ),
      }] : []}
    />
  );
}
