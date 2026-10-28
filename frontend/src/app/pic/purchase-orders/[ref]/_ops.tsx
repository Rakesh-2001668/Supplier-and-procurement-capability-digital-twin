'use client';

import { useState } from 'react';
import { Button, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date, dateTime, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- shared types
export type OpsPo = { number: string; status: string; version: number;
  lines: { line_no: number; description: string; qty: string; uom: string; need_date: string }[] };
export type ScheduleRow = { line: number; seq: number; description: string; uom: string; qty: string; deliveryDate: string; confirmedDate: string | null;
  receivedQty: string; openQty: string; status: string; daysLate: number };
export type Transmission = { id: string; version: number; channel: string; format: string; recipient: string | null; status: string; sha256: string;
  bytes: number; sentAt: string | null; ackAt: string | null; error: string | null; createdAt: string };
type TransmissionDetail = Transmission & { document: string; segments?: { segments: number; declared: number; type: string } };

const EDITABLE = ['DRAFT', 'IN_APPROVAL', 'RELEASED', 'TRANSMITTED', 'CONFIRMED'];
const FILE_EXT: Record<string, string> = { EDIFACT_ORDERS: 'edi', EDIFACT_ORDCHG: 'edi', HTML_EMAIL: 'html', PORTAL: 'json' };

/** Download an API file through the same-origin proxy (the session cookie authorises it). */
export async function downloadFile(path: string, fileName: string) {
  const response = await fetch(`/api/pic/v1${path}`, { cache: 'no-store' });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new ApiError({ status: response.status, code: problem.code ?? 'ERROR', ...problem });
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

/** EDIFACT segments one per line, honouring the release character (?). */
function edifactSegments(document: string): string[] {
  const text = document.startsWith('UNA') ? document.slice(9) : document;
  const out: string[] = document.startsWith('UNA') ? [document.slice(0, 9)] : [];
  let current = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '?' && i + 1 < text.length) {
      current += ch + text[i + 1];
      i++;
    } else if (ch === "'") {
      out.push(`${current}'`);
      current = '';
    } else if (ch !== '\n' && ch !== '\r') {
      current += ch;
    }
  }
  if (current.trim()) out.push(current);
  return out;
}

// ---------------------------------------------------------------- Schedule tab
export function ScheduleTab({ po, canEdit }: { po: OpsPo; canEdit: boolean }) {
  const { data, isLoading, error } = useApi<ScheduleRow[]>(`/purchase-orders/${encodeURIComponent(po.number)}/schedule`);
  const [editing, setEditing] = useState<number | null>(null);
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  const editable = canEdit && EDITABLE.includes(po.status);
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Delivery schedule per PO line. Receipts fill the earliest open schedule line first; lateness is measured against the supplier&apos;s confirmed date.
        {editable && (po.status === 'CONFIRMED'
          ? ' The order is confirmed: a schedule change creates a new version that the supplier re-confirms.'
          : ' Until the supplier confirms, schedule changes are made in place (audited).')}
      </p>
      {!data?.length ? <Empty title="No schedule lines" hint="Orders migrated before delivery schedules existed are expedited on the line need date." /> : (
        <DataTable<ScheduleRow> rows={data.map((r) => ({ ...r, id: `${r.line}-${r.seq}` }))} columns={[
          { key: 'line', header: 'Line' },
          { key: 'seq', header: 'Schedule' },
          { key: 'description', header: 'Item' },
          { key: 'qty', header: 'Quantity', align: 'right', render: (r) => qty(r.qty, r.uom) },
          { key: 'deliveryDate', header: 'Requested', render: (r) => date(r.deliveryDate) },
          { key: 'confirmedDate', header: 'Confirmed', render: (r) => r.confirmedDate ? date(r.confirmedDate) : <span className="text-slate-500">not yet</span> },
          { key: 'receivedQty', header: 'Received', align: 'right', render: (r) => qty(r.receivedQty) },
          { key: 'openQty', header: 'Open', align: 'right', render: (r) => qty(r.openQty) },
          { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.daysLate > 0 ? 'OVERDUE' : r.status} /> },
          { key: 'daysLate', header: 'Days late', align: 'right', render: (r) => r.daysLate ? <span className="font-semibold text-red-700">{r.daysLate}</span> : '0' },
        ]} />
      )}
      {editable && (
        <div className="flex flex-wrap gap-2">
          {po.lines.map((l) => <Button key={l.line_no} onClick={() => setEditing(l.line_no)}>Edit schedule · line {l.line_no}</Button>)}
        </div>
      )}
      {editing !== null && <ScheduleEditDialog po={po} lineNo={editing} current={(data ?? []).filter((r) => r.line === editing)} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ScheduleEditDialog({ po, lineNo, current, onClose }: { po: OpsPo; lineNo: number; current: ScheduleRow[]; onClose: () => void }) {
  const line = po.lines.find((l) => l.line_no === lineNo)!;
  const [rows, setRows] = useState(current.length ? current.map((r) => ({ qty: String(Number(r.qty)), deliveryDate: r.deliveryDate }))
    : [{ qty: String(Number(line.qty)), deliveryDate: line.need_date }]);
  const [reason, setReason] = useState('');
  const total = rows.reduce((s, r) => s + (Number(r.qty) || 0), 0);
  const balanced = Math.abs(total - Number(line.qty)) < 1e-9;
  const complete = rows.every((r) => Number(r.qty) > 0 && r.deliveryDate);
  const versioned = po.status === 'CONFIRMED';
  const save = useCommand(() => api.put<{ mode: string; version: number }>(`/purchase-orders/${encodeURIComponent(po.number)}/lines/${lineNo}/schedule`,
    { lines: rows, reason: reason.trim() || undefined }), {
    success: (r) => r.mode === 'NEW_VERSION' ? `Version ${r.version} sent to the supplier for re-confirmation` : 'Delivery schedule updated',
    onSuccess: onClose,
  });
  const update = (i: number, patch: Partial<{ qty: string; deliveryDate: string }>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <Dialog open title={`Delivery schedule · ${po.number} line ${lineNo}${versioned ? ` (creates version ${po.version + 1})` : ''}`} onClose={onClose}>
      <p className="text-sm text-slate-600">{line.description} · ordered {qty(line.qty, line.uom)}</p>
      <div className="mt-3 space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
            <Field label={`Quantity ${i + 1}`}>{(id) => <Input id={id} inputMode="decimal" value={r.qty} onChange={(e) => update(i, { qty: e.target.value })} />}</Field>
            <Field label="Delivery date">{(id) => <Input id={id} type="date" value={r.deliveryDate} onChange={(e) => update(i, { deliveryDate: e.target.value })} />}</Field>
            <Button variant="ghost" aria-label={`Remove schedule line ${i + 1}`} disabled={rows.length === 1} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button onClick={() => setRows((rs) => [...rs, { qty: '', deliveryDate: rs[rs.length - 1]?.deliveryDate ?? line.need_date }])}>Add delivery</Button>
      </div>
      <p className={`mt-3 text-sm ${balanced ? 'text-slate-600' : 'text-amber-700'}`} role="status">
        Scheduled {qty(total)} of {qty(line.qty, line.uom)}{balanced ? '' : ' — the schedule must add up to the line quantity'}
      </p>
      <div className="mt-3">
        <Field label={versioned ? 'Reason (sent with the new version)' : 'Reason (audited)'}>{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!balanced || !complete || (versioned && !reason.trim())} busy={save.isPending} onClick={() => save.mutate()}>
          {versioned ? 'Send new version' : 'Save schedule'}
        </Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- supplier confirmation with dates per schedule line
export function ScheduleConfirmDialog({ po, onClose }: { po: OpsPo; onClose: () => void }) {
  const { data, isLoading, error } = useApi<ScheduleRow[]>(`/purchase-orders/${encodeURIComponent(po.number)}/schedule`);
  const [dates, setDates] = useState<Record<string, string>>({});
  const [note, setNote] = useState('');
  const key = (r: ScheduleRow) => `${r.line}-${r.seq}`;
  const value = (r: ScheduleRow) => dates[key(r)] ?? r.deliveryDate;
  const later = (data ?? []).filter((r) => value(r) > r.deliveryDate);
  const confirm = useCommand(() => {
    const byLine = new Map<number, { seq: number; confirmedDate: string }[]>();
    for (const r of data ?? []) byLine.set(r.line, [...(byLine.get(r.line) ?? []), { seq: r.seq, confirmedDate: value(r) }]);
    return api.post<{ confirmation?: string; outsideTolerance?: string[] }>(`/purchase-orders/${encodeURIComponent(po.number)}/confirmations`, {
      status: 'CONFIRMED', note: note.trim() || undefined,
      lines: [...byLine.entries()].map(([line, scheduleConfirmations]) => ({ line, scheduleConfirmations })),
    });
  }, {
    success: (r) => r.confirmation === 'CHANGE_REQUESTED' ? `Later dates sent to the buyer for review: ${(r.outsideTolerance ?? []).join('; ')}` : `${po.number} confirmed`,
    onSuccess: onClose,
  });
  return (
    <Dialog open title={`Confirm ${po.number} v${po.version} · delivery dates`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : !data?.length ? <Empty title="No schedule lines on this order" /> : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-3 py-2">Line</th><th className="px-3 py-2">Item</th><th className="px-3 py-2 text-right">Quantity</th><th className="px-3 py-2">Requested</th><th className="px-3 py-2">You confirm</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((r) => (
                <tr key={key(r)}>
                  <td className="px-3 py-2">{r.line}/{r.seq}</td>
                  <td className="px-3 py-2">{r.description}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{qty(r.qty, r.uom)}</td>
                  <td className="px-3 py-2">{date(r.deliveryDate)}</td>
                  <td className="px-3 py-2"><Input aria-label={`Confirmed date ${r.line}/${r.seq}`} type="date" value={value(r)} onChange={(e) => setDates((d) => ({ ...d, [key(r)]: e.target.value }))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3"><Field label="Note to the buyer (optional)">{(id) => <Textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field></div>
      <p className={`mt-2 text-xs ${later.length ? 'text-amber-700' : 'text-slate-500'}`} role="status">
        {later.length ? `${later.length} date(s) are later than requested: the confirmation goes back to the buyer as a change request.` : 'Dates on or before the requested date confirm the order directly.'}
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!data?.length} busy={confirm.isPending} onClick={() => confirm.mutate()}>Confirm order</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Transmissions tab (portal / EDI / e-mail)
export function TransmissionsTab({ po, canResend }: { po: OpsPo; canResend: boolean }) {
  const path = `/purchase-orders/${encodeURIComponent(po.number)}/transmissions`;
  const { data, isLoading, error } = useApi<Transmission[]>(path);
  const [open, setOpen] = useState<Transmission | null>(null);
  const resend = useCommand((id: string) => api.post<Transmission>(`${path}/${id}/resend`), {
    success: (r) => `${r.channel} transmission ${r.status.toLowerCase()}${r.error ? ` · ${r.error}` : ''}`,
  });
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.length) return <Empty title="Not transmitted yet" hint="The order is sent when it is released." />;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">Every version is sent over the portal and, where agreed with the supplier, as EDIFACT (ORDERS, ORDCHG for changes) and by e-mail. The exact document and its SHA-256 are kept.</p>
      <DataTable<Transmission> rows={data} columns={[
        { key: 'version', header: 'Version', render: (t) => `v${t.version}` },
        { key: 'channel', header: 'Channel' },
        { key: 'format', header: 'Format', render: (t) => <span className="font-mono text-xs">{t.format}</span> },
        { key: 'recipient', header: 'Recipient', render: (t) => t.recipient ?? '–' },
        { key: 'status', header: 'Status', render: (t) => <StatusChip status={t.status} /> },
        { key: 'sentAt', header: 'Sent', render: (t) => dateTime(t.sentAt) },
        { key: 'ackAt', header: 'Acknowledged', render: (t) => dateTime(t.ackAt) },
        { key: 'error', header: 'Delivery note', render: (t) => t.error ? <span className="text-xs text-amber-800">{t.error}</span> : '–' },
        { key: 'sha256', header: 'SHA-256', render: (t) => <span className="font-mono text-[11px] text-slate-500" title={t.sha256}>{t.sha256.slice(0, 12)}</span> },
        { key: 'actions', header: '', render: (t) => (
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setOpen(t)}>View</Button>
            {canResend && t.version === po.version && t.channel !== 'PORTAL' && ['QUEUED', 'FAILED'].includes(t.status) && (
              <Button busy={resend.isPending} onClick={() => resend.mutate(t.id)}>Re-send</Button>
            )}
          </div>
        ) },
      ]} />
      {open && <DocumentDialog po={po.number} transmission={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function DocumentDialog({ po, transmission, onClose }: { po: string; transmission: Transmission; onClose: () => void }) {
  const path = `/purchase-orders/${encodeURIComponent(po)}/transmissions/${transmission.id}`;
  const { data, isLoading, error } = useApi<TransmissionDetail>(path);
  const [downloadError, setDownloadError] = useState<Error | null>(null);
  const fileName = `${po}_v${transmission.version}_${transmission.channel.toLowerCase()}.${FILE_EXT[transmission.format] ?? 'txt'}`;
  return (
    <Dialog open title={`${transmission.channel} · ${transmission.format} · v${transmission.version}`} onClose={onClose}>
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">
            {data.recipient ? `To ${data.recipient} · ` : ''}{data.bytes.toLocaleString('en-IN')} bytes · SHA-256 <span className="font-mono">{data.sha256}</span>
            {data.segments && ` · ${data.segments.type}: ${data.segments.segments} segments (UNT ${data.segments.declared})`}
          </p>
          {data.format.startsWith('EDIFACT') ? (
            <ol className="max-h-96 overflow-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100">
              {edifactSegments(data.document).map((s, i) => <li key={i}><span className="mr-3 inline-block w-6 select-none text-right text-slate-500">{i + 1}</span>{s}</li>)}
            </ol>
          ) : data.format === 'HTML_EMAIL' ? (
            <iframe title="E-mail document" sandbox="" srcDoc={data.document} className="h-96 w-full rounded-lg border border-slate-200 bg-white" />
          ) : (
            <pre className="max-h-96 overflow-auto rounded-lg bg-slate-50 p-3 text-xs">{data.document}</pre>
          )}
          <ProblemBox error={downloadError} />
          <div className="flex justify-end gap-2">
            <Button onClick={() => downloadFile(`${path}/document`, fileName).catch(setDownloadError)}>Download</Button>
            <Button variant="primary" onClick={onClose}>Close</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
