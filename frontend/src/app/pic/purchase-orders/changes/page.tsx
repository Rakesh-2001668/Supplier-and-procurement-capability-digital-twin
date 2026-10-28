'use client';

import Link from 'next/link';
import { Card, DataTable, Empty, Kpi, LinkButton, Loading, PageHeader, ProblemBox, StatusChip, Tabs } from '@/components/pic/ui';
import { date, dateTime, qty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

type ChangeLine = { line: string | number; qty?: string; need_date?: string };
type Awaiting = { po: string; supplier: string | null; version: number; dueAt: string | null; overdue: boolean };
type Confirmation = { po: string; supplier: string | null; version: number; status: string; hoursToConfirm: string | null; note: string | null;
  lines: ChangeLine[]; at: string };
type ChangeRequest = { number: string; po: string; supplier: string | null; fromVersion: number; origin: string; lines: ChangeLine[]; reason: string;
  status: string; resultVersion: number | null; decisionComment: string | null; at: string };
type Version = { po: string; version: number; reason: string | null; changes: ChangeLine[] | null; at: string };
type View = { awaiting: Awaiting[]; confirmations: Confirmation[]; changeRequests: ChangeRequest[]; versions: Version[]; confirmationSlaHours: number;
  withinSlaPct: string | null; changeRatePct: string | null };
type Task = { id: string; kind: string; object_ref: string };

const poLink = (po: string) => <Link href={`/pic/purchase-orders/${encodeURIComponent(po)}`} className="font-medium text-[#1A56DB] hover:underline">{po}</Link>;

function changeText(lines: ChangeLine[] | null | undefined) {
  if (!lines?.length) return <span className="text-slate-400">–</span>;
  return (
    <ul className="space-y-0.5 text-xs">
      {lines.map((l, i) => (
        <li key={i}>Line {l.line}: {[l.qty !== undefined && `qty → ${qty(l.qty)}`, l.need_date && `date → ${date(l.need_date)}`].filter(Boolean).join(', ') || 'no change'}</li>
      ))}
    </ul>
  );
}

export default function PoConfirmations() {
  const { data, isLoading, error } = useApi<View>('/po-confirmations');
  const tasks = useApi<Task[]>('/tasks');
  const pendingTasks = (tasks.data ?? []).filter((t) => t.kind === 'PO_CHANGE_REQUEST');

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PO-03 · Confirmations & changes" title="Order confirmations and changes"
        subtitle="Suppliers confirm each PO version within the confirmation SLA. Qty and date change requests from either side go to the buyer; accepting one creates the next PO version, which the supplier re-confirms."
        actions={<>
          <LinkButton href="/pic/purchase-orders">Purchase orders</LinkButton>
          <LinkButton href="/pic/purchase-orders/expediting">Expediting cockpit</LinkButton>
        </>} />

      {isLoading ? <Loading /> : error || !data ? <ProblemBox error={error} /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Awaiting confirmation" value={data.awaiting.length}
              hint={`${data.awaiting.filter((a) => a.overdue).length} past the ${data.confirmationSlaHours} h SLA`}
              tone={data.awaiting.some((a) => a.overdue) ? 'bad' : data.awaiting.length ? 'warn' : 'default'} />
            <Kpi label="Confirmed within SLA" value={data.withinSlaPct === null ? '–' : `${data.withinSlaPct}%`}
              hint={`target ≤ ${data.confirmationSlaHours} h from transmission`} tone={data.withinSlaPct !== null && Number(data.withinSlaPct) >= 90 ? 'good' : 'warn'} />
            <Kpi label="Change rate" value={data.changeRatePct === null ? '–' : `${data.changeRatePct}%`} hint="share of POs with more than one version" />
            <Kpi label="Open change requests" value={data.changeRequests.filter((r) => r.status === 'OPEN').length}
              hint={`${data.changeRequests.length} raised in total`} tone={data.changeRequests.some((r) => r.status === 'OPEN') ? 'warn' : 'default'} />
          </div>

          {pendingTasks.length > 0 && (
            <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
              {pendingTasks.length} change request{pendingTasks.length === 1 ? '' : 's'} ({pendingTasks.map((t) => t.object_ref).join(', ')}) waiting for your decision.{' '}
              <Link href="/pic/tasks" className="font-semibold underline">Decide in the task inbox</Link>
            </p>
          )}

          <Card title="Awaiting supplier confirmation">
            <DataTable<Awaiting> rows={data.awaiting} empty="Every transmitted PO has been confirmed" columns={[
              { key: 'po', header: 'PO', render: (r) => poLink(r.po) },
              { key: 'supplier', header: 'Supplier', render: (r) => r.supplier ?? '–' },
              { key: 'version', header: 'Version', align: 'right', render: (r) => `v${r.version}` },
              { key: 'dueAt', header: 'Confirm by', render: (r) => dateTime(r.dueAt) },
              { key: 'overdue', header: 'SLA', render: (r) => <StatusChip status={r.overdue ? 'OVERDUE' : 'PENDING'} /> },
            ]} />
          </Card>

          <Card>
            <Tabs tabs={[
              { id: 'requests', label: `Change requests (${data.changeRequests.length})`, content: (
                <div className="space-y-3">
                  <p className="text-sm text-slate-600">
                    A buyer accepts or rejects each request from the <Link href="/pic/tasks" className="font-medium text-[#1A56DB] hover:underline">task inbox</Link> (tasks
                    of kind PO change request). Price changes are not allowed here; they go through the contract.
                  </p>
                  <DataTable<ChangeRequest> rows={data.changeRequests} empty="No change requests yet" columns={[
                    { key: 'number', header: 'Request', render: (r) => <span className="font-mono text-xs font-semibold">{r.number}</span> },
                    { key: 'po', header: 'PO', render: (r) => poLink(r.po) },
                    { key: 'supplier', header: 'Supplier', render: (r) => r.supplier ?? '–' },
                    { key: 'origin', header: 'From', render: (r) => <span className="text-xs">{r.origin === 'SUPPLIER' ? 'Supplier' : 'Buyer'} · v{r.fromVersion}</span> },
                    { key: 'lines', header: 'Requested change', render: (r) => changeText(r.lines) },
                    { key: 'reason', header: 'Reason', className: 'min-w-[220px] max-w-md' },
                    { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
                    { key: 'resultVersion', header: 'Outcome', className: 'min-w-[160px]', render: (r) => (
                      <span className="text-xs">
                        {r.resultVersion ? `Created v${r.resultVersion}` : r.status === 'OPEN' ? <Link href="/pic/tasks" className="font-medium text-[#1A56DB] hover:underline">Awaiting buyer</Link> : '–'}
                        {r.decisionComment && <span className="block text-slate-500">“{r.decisionComment}”</span>}
                      </span>
                    ) },
                    { key: 'at', header: 'Raised', render: (r) => <span className="whitespace-nowrap">{dateTime(r.at)}</span> },
                  ]} />
                </div>
              ) },
              { id: 'confirmations', label: `Confirmations (${data.confirmations.length})`, content: (
                <DataTable<Confirmation> rows={data.confirmations} empty="No confirmations received yet" columns={[
                  { key: 'po', header: 'PO', render: (r) => poLink(r.po) },
                  { key: 'supplier', header: 'Supplier', render: (r) => r.supplier ?? '–' },
                  { key: 'version', header: 'Version', align: 'right', render: (r) => `v${r.version}` },
                  { key: 'status', header: 'Response', render: (r) => <StatusChip status={r.status} /> },
                  { key: 'hoursToConfirm', header: 'Hours to confirm', align: 'right', render: (r) => r.hoursToConfirm === null ? '–' : (
                    <span className={Number(r.hoursToConfirm) > data.confirmationSlaHours ? 'font-semibold text-red-700' : ''}>{Number(r.hoursToConfirm).toFixed(1)} h</span>
                  ) },
                  { key: 'lines', header: 'Proposed change', render: (r) => changeText(r.lines) },
                  { key: 'note', header: 'Note', className: 'max-w-sm', render: (r) => r.note ?? '–' },
                  { key: 'at', header: 'Received', render: (r) => <span className="whitespace-nowrap">{dateTime(r.at)}</span> },
                ]} />
              ) },
              { id: 'versions', label: `Version history (${data.versions.length})`, content: data.versions.length ? (
                <DataTable<Version> rows={data.versions} columns={[
                  { key: 'po', header: 'PO', render: (r) => poLink(r.po) },
                  { key: 'version', header: 'Version', align: 'right', render: (r) => `v${r.version}` },
                  { key: 'changes', header: 'Changes', render: (r) => changeText(r.changes) },
                  { key: 'reason', header: 'Reason', className: 'min-w-[240px] max-w-lg', render: (r) => r.reason ?? '–' },
                  { key: 'at', header: 'When', render: (r) => <span className="whitespace-nowrap">{dateTime(r.at)}</span> },
                ]} />
              ) : <Empty title="No PO has been changed yet" hint="Every change creates a new version that the supplier must re-confirm." /> },
            ]} />
          </Card>
        </>
      )}
    </div>
  );
}
