'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { downloadFile } from '../purchase-orders/[ref]/_ops';
import { today } from './_components';

// ---------------------------------------------------------------- GST e-invoice verification (TD §12.3)
type Check = { code: string; ok: boolean; detail: string };
type EInvoice = { invoice: string; irn: string | null; irnValid: boolean | null; level: 'IRP' | 'LOCAL' | null; valid: boolean | null; checks: Check[];
  irpError?: string | null; qrPresent?: boolean; verifiedAt: string | null; verifiedBy?: string; irpConfigured: boolean };

export function EInvoiceBadge({ invoiceRef }: { invoiceRef: string }) {
  const { data } = useApi<EInvoice>(`/invoices/${invoiceRef}/e-invoice`);
  if (!data || !data.irn) return <span className="text-slate-500">no IRN</span>;
  if (data.valid === false) return <StatusChip status="FAILED" />;
  return (
    <span className="inline-flex items-center gap-1.5">
      <StatusChip status={data.valid ? 'VALID' : 'PENDING'} />
      <span className="text-xs text-slate-600">{data.level === 'IRP' ? 'verified at IRP' : 'local check'}</span>
    </span>
  );
}

export function EInvoicePanel({ invoiceRef, canVerify }: { invoiceRef: string; canVerify: boolean }) {
  const { data, isLoading, error } = useApi<EInvoice>(`/invoices/${invoiceRef}/e-invoice`);
  const [qr, setQr] = useState('');
  const [open, setOpen] = useState(false);
  const verify = useCommand(() => api.post<EInvoice>(`/invoices/${invoiceRef}/e-invoice/verify`, { signedQr: qr.trim() || undefined }, { idempotencyKey: false }), {
    success: (r) => `E-invoice ${r.valid ? 'verified' : 'NOT valid'} (${r.level === 'IRP' ? 'IRP' : 'local check'})`,
    onSuccess: () => { setOpen(false); setQr(''); },
  });
  if (isLoading) return <Loading />;
  if (error) return <ProblemBox error={error} />;
  if (!data?.irn) return <Empty title="Not an e-invoice" hint="No IRN was captured with this invoice." />;
  const tone = data.valid ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-red-200 bg-red-50 text-red-900';
  return (
    <div className="space-y-3">
      <div className={`rounded-lg border p-3 text-sm ${tone}`}>
        <p className="font-semibold">
          {data.valid ? 'IRN valid' : 'IRN not valid'} · {data.level === 'IRP' ? 'verified at the Invoice Registration Portal' : 'verified locally'}
        </p>
        <p className="mt-0.5 text-xs">
          {data.level === 'IRP'
            ? 'The IRN was looked up at the IRP through the GSP.'
            : `IRN format and hash checked${data.qrPresent ? ' and the signed QR payload decoded' : ''}; the NIC signature is not verified locally${data.irpConfigured ? '' : ' (IRP access is not configured)'}.`}
          {data.irpError ? ` IRP lookup failed: ${data.irpError}.` : ''}
        </p>
        {data.verifiedAt && <p className="mt-0.5 text-xs opacity-80">Checked {dateTime(data.verifiedAt)}{data.verifiedBy ? ` by ${data.verifiedBy}` : ''}</p>}
      </div>
      {data.checks.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
          {data.checks.map((c) => (
            <li key={c.code} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span><span className="font-mono text-xs text-slate-500">{c.code}</span> · {c.detail}</span>
              <StatusChip status={c.ok ? 'OK' : 'FAILED'} />
            </li>
          ))}
        </ul>
      )}
      <p className="break-all font-mono text-[11px] text-slate-500">IRN {data.irn}</p>
      {canVerify && <Button onClick={() => setOpen(true)}>Verify again</Button>}
      {open && (
        <Dialog open title="Verify e-invoice" onClose={() => setOpen(false)}>
          <Field label="Signed QR code (optional)" hint="The JWT printed as the e-invoice QR. Its payload is decoded and compared with the invoice.">
            {(id) => <Textarea id={id} value={qr} onChange={(e) => setQr(e.target.value)} className="font-mono text-xs" />}
          </Field>
          <p className="mt-2 text-xs text-slate-500">A changed result updates the IRN flag; run the match again to clear or raise the tax exception.</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" busy={verify.isPending} onClick={() => verify.mutate()}>Verify</Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- bank payment files (F7-07)
type Run = { run: string; valueDate: string; payments: number; totalMinor: number; companyCodes: string[]; files: { number: string; format: string; status: string }[] };
type PaymentFile = { id: string; number: string; run: string; format: string; fileName: string; sha256: string; payments: number; totalMinor: number;
  status: string; bankRef: string | null; sentAt: string | null; createdAt: string };
type FileList = { items: PaymentFile[]; bankConnector: { type: string; configured: boolean; detail: string } };

const FORMATS = [{ value: 'ISO20022_PAIN001', label: 'ISO 20022 pain.001 (XML)' }, { value: 'NEFT_CSV', label: 'NEFT bulk CSV' }];
const NEXT: Record<string, string[]> = { GENERATED: ['SENT', 'REJECTED'], SENT: ['ACKNOWLEDGED', 'REJECTED'] };

export function PaymentFilesCard({ canManage }: { canManage: boolean }) {
  const runs = useApi<Run[]>('/payments/runs');
  const files = useApi<FileList>('/payment-files');
  const [formats, setFormats] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<PaymentFile | null>(null);
  const [downloadError, setDownloadError] = useState<Error | null>(null);
  const generate = useCommand((run: string) => api.post<PaymentFile>(`/payments/runs/${encodeURIComponent(run)}/file`, { format: formats[run] ?? 'ISO20022_PAIN001' }), {
    success: (f) => `${f.fileName} generated · ${f.payments} payment(s) · ${inr(f.totalMinor)}`,
  });
  const live = (r: Run) => r.files.find((f) => f.status !== 'REJECTED');
  return (
    <Card title="Bank payment files · payment runs">
      {runs.isLoading || files.isLoading ? <Loading /> : runs.error ? <ProblemBox error={runs.error} /> : files.error ? <ProblemBox error={files.error} /> : (
        <div className="space-y-5">
          <p className="text-sm text-slate-600">
            Each payment run is sent to the bank once, as an ISO 20022 pain.001 credit-transfer file or a NEFT bulk file. Creditor accounts are decrypted only
            into the file; every download is audited. {files.data?.bankConnector.detail}.
          </p>
          {!runs.data?.length ? <Empty title="No payment runs yet" /> : (
            <DataTable<Run> rows={runs.data.map((r) => ({ ...r, id: r.run }))} columns={[
              { key: 'run', header: 'Run', render: (r) => <span className="font-mono">{r.run}</span> },
              { key: 'valueDate', header: 'Value date', render: (r) => date(r.valueDate) },
              { key: 'payments', header: 'Payments', align: 'right' },
              { key: 'totalMinor', header: 'Amount', align: 'right', render: (r) => inr(r.totalMinor) },
              { key: 'files', header: 'Bank file', render: (r) => r.files.length
                ? r.files.map((f) => <span key={f.number} className="mr-2 inline-flex items-center gap-1 text-xs">{f.number} <StatusChip status={f.status} /></span>)
                : <span className="text-slate-500">none</span> },
              { key: 'action', header: '', render: (r) => canManage && !live(r) ? (
                <div className="flex items-center gap-2">
                  <Select aria-label={`File format for ${r.run}`} value={formats[r.run] ?? 'ISO20022_PAIN001'} options={FORMATS}
                    onChange={(e) => setFormats((f) => ({ ...f, [r.run]: e.target.value }))} className="w-48" />
                  <Button variant="primary" busy={generate.isPending && generate.variables === r.run} onClick={() => generate.mutate(r.run)}>Generate</Button>
                </div>
              ) : null },
            ]} />
          )}
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-900">Generated files</h3>
            <ProblemBox error={downloadError} />
            <DataTable<PaymentFile> rows={files.data?.items ?? []} empty="No payment files generated" columns={[
              { key: 'number', header: 'File', render: (f) => <span className="font-mono">{f.number}</span> },
              { key: 'run', header: 'Run' },
              { key: 'format', header: 'Format', render: (f) => label(f.format) },
              { key: 'payments', header: 'Payments', align: 'right' },
              { key: 'totalMinor', header: 'Amount', align: 'right', render: (f) => inr(f.totalMinor) },
              { key: 'status', header: 'Status', render: (f) => <StatusChip status={f.status} /> },
              { key: 'bankRef', header: 'Bank ref.', render: (f) => f.bankRef ?? '–' },
              { key: 'createdAt', header: 'Generated', render: (f) => dateTime(f.createdAt) },
              { key: 'sha256', header: 'SHA-256', render: (f) => <span className="font-mono text-[11px] text-slate-500" title={f.sha256}>{f.sha256.slice(0, 12)}</span> },
              { key: 'action', header: '', render: (f) => canManage ? (
                <div className="flex gap-2">
                  <Button onClick={() => { setDownloadError(null); downloadFile(`/payment-files/${encodeURIComponent(f.number)}/content`, f.fileName).catch(setDownloadError); }}>Download</Button>
                  {NEXT[f.status] && <Button onClick={() => setStatus(f)}>Record bank status</Button>}
                </div>
              ) : null },
            ]} />
          </div>
        </div>
      )}
      {status && <FileStatusDialog file={status} onClose={() => setStatus(null)} />}
    </Card>
  );
}

function FileStatusDialog({ file, onClose }: { file: PaymentFile; onClose: () => void }) {
  const options = NEXT[file.status] ?? [];
  const [next, setNext] = useState(options[0]);
  const [bankRef, setBankRef] = useState(file.bankRef ?? '');
  const [reason, setReason] = useState('');
  const save = useCommand(() => api.post<PaymentFile>(`/payment-files/${encodeURIComponent(file.number)}/status`,
    { status: next, bankRef: bankRef.trim() || undefined, reason: reason.trim() || undefined }), {
    success: (f) => `${f.number} ${f.status.toLowerCase()}`, onSuccess: onClose,
  });
  const missing = (next === 'ACKNOWLEDGED' && !bankRef.trim()) || (next === 'REJECTED' && !reason.trim());
  return (
    <Dialog open title={`Bank status · ${file.number}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Status">{(id) => <Select id={id} value={next} onChange={(e) => setNext(e.target.value)} options={options.map((o) => ({ value: o, label: label(o) }))} />}</Field>
        <Field label={next === 'ACKNOWLEDGED' ? 'Bank reference (required)' : 'Bank reference'}>{(id) => <Input id={id} maxLength={60} value={bankRef} onChange={(e) => setBankRef(e.target.value)} />}</Field>
        <div className="md:col-span-2">
          <Field label={next === 'REJECTED' ? 'Reason (required)' : 'Note'}>{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-500">Record what the bank did with the uploaded file. A rejected file can be regenerated for the same run.</p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!next || missing} busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- consignment settlement (P08 self-billing, ERS)
type SupplierRef = { code: string; name: string; status: string };
type Settlement = { id: string; number: string; status: string; gross_minor: number };

/** Roles that run consignment self-billing (scope invoice:post or payment:run; the service also checks the role). */
export const SETTLE_ROLES = ['AP_CLERK', 'FINANCE_CONTROLLER'];

/** One AP document for everything withdrawn from a supplier's consignment stock up to a date and not yet settled. */
export function ConsignmentSettlementDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const reference = useApi<{ suppliers: SupplierRef[] }>('/reference');
  const [supplier, setSupplier] = useState('');
  const [periodTo, setPeriodTo] = useState(today());
  const [companyCode, setCompanyCode] = useState('1000');
  const [taxInvoice, setTaxInvoice] = useState('');
  const settle = useCommand(() => api.post<Settlement>('/consignment/settlements', {
    supplier, period_to: periodTo, company_code: companyCode.trim() || '1000', reference: taxInvoice.trim() || undefined,
  }), {
    success: (r) => `${r.number} created · ${inr(r.gross_minor)} · ${r.status.replace(/_/g, ' ').toLowerCase()}`,
    onSuccess: (r) => { onClose(); router.push(`/pic/invoices/${r.id}`); },
  });
  return (
    <Dialog open title="Consignment settlement (self-billing)" onClose={onClose}>
      {reference.error && <ProblemBox error={reference.error} />}
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Consignor (supplier)">
          {(id) => <Select id={id} value={supplier} onChange={(e) => setSupplier(e.target.value)}
            options={[{ value: '', label: reference.isLoading ? 'Loading…' : 'Choose a supplier' },
              ...(reference.data?.suppliers ?? []).map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }))]} />}
        </Field>
        <Field label="Settle withdrawals up to (inclusive)">
          {(id) => <Input id={id} type="date" required value={periodTo} max={today()} onChange={(e) => setPeriodTo(e.target.value)} />}
        </Field>
        <Field label="Company code">
          {(id) => <Input id={id} maxLength={4} value={companyCode} onChange={(e) => setCompanyCode(e.target.value)} />}
        </Field>
        <Field label="Supplier tax invoice (optional)" hint="Where the consignor issues a GST tax invoice for the withdrawn quantity">
          {(id) => <Input id={id} maxLength={60} value={taxInvoice} onChange={(e) => setTaxInvoice(e.target.value)} />}
        </Field>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Withdrawals from consignment stock (201K consumption, 411K transfer) create the liability; this settles everything withdrawn up to the date and not yet
        settled, priced at the consignment PO line with its GST rate and HSN. The document is duplicate-checked and ERS-matched (settled ≤ withdrawn), then
        approved and posted like any invoice.
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!supplier || !periodTo} busy={settle.isPending} onClick={() => settle.mutate()}>Create settlement</Button>
      </div>
    </Dialog>
  );
}
