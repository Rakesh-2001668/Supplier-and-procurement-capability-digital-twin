'use client';

import { useMemo, useState, useSyncExternalStore } from 'react';
import { Button, Dialog, Empty, Field, Input, Loading, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api, readSessionUser, SessionUser } from '@/lib/pic/api';
import { inr, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand, useList } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- shared helpers (used by invoices, receiving and portal)

/** Signed-in user from the display cookie; undefined until read on the client (avoids hydration mismatch). */
const noSubscribe = () => () => {};
export function useSessionUser(): SessionUser | null | undefined {
  const cookie = useSyncExternalStore(noSubscribe, () => document.cookie, () => null);
  return useMemo(() => (cookie === null ? undefined : readSessionUser()), [cookie]);
}

export function hasRole(user: SessionUser | null | undefined, ...roles: string[]) {
  return !!user && roles.some((r) => user.roles.includes(r));
}

/** Today's business date in India (IST), YYYY-MM-DD; toISOString() would give the UTC date before 05:30 IST. */
export const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' })
  .format(new Date());

export function isNumber(v: string) {
  return v.trim() !== '' && !Number.isNaN(Number(v));
}

export function isPositive(v: string) {
  return isNumber(v) && Number(v) > 0;
}

/** Decimal-string arithmetic is good enough for display/defaults; the API re-validates exactly. */
export function minus(a: string | number, b: string | number) {
  const r = Number(a) - Number(b);
  return r > 0 ? String(Number(r.toFixed(3))) : '0';
}

// ---------------------------------------------------------------- types
export type PoLine = { id: string; line_no: number; description: string; qty: string; uom: string; unit_price_minor: number; net_minor: number;
  need_date: string; gst_rate: string; hsn_code: string | null; storage_location: string | null; purchase_type: string; shipped_qty: string;
  received_qty: string; accepted_qty: string; rejected_qty: string; invoiced_qty: string; invoiced_minor: number; ses_approved_minor: number;
  gr_required: boolean; ses_required: boolean; quality_managed: boolean };
export type PoDetail = { id: string; number: string; status: string; version: number; supplier: { code: string; name: string };
  total_minor: number; payment_terms: string; lines: PoLine[] };
export type PoRow = { id: string; number: string; supplier_code: string; status: string; total_minor: number; created_at: string };

export type InvoiceRow = { id: string; number: string; supplier_invoice_no: string; supplier_code: string; company_code: string; invoice_date: string;
  channel: string; net_minor: number; tax_minor: number; gross_minor: number; status: string; match_type: string | null;
  first_pass_matched: boolean | null; payment_block: boolean | null; due_date: string | null; erp_doc_no: string | null;
  payment_status: string | null; open_exceptions: number };

// ---------------------------------------------------------------- capture / submit invoice (INV-01, SLM-05)
type DraftLine = { include: boolean; line: PoLine; qty: string; unit_price: string; gst_rate: string; hsn: string };

/** What the document-capture engine read from an invoice PDF/image (POST /invoices/documents). Nothing is stored server-side. */
type Extracted = {
  header: { supplierGstin: string | null; supplierInvoiceNo: string | null; invoiceDate: string | null; irn: string | null; poNumber: string | null;
    netMinor: number | null; taxMinor: number | null; grossMinor: number | null };
  supplier: { code: string; name: string } | null;
  lines: { po: string | null; po_line: number | string; description: string | null; hsn: string | null; qty: string | null; unit_price: string | null;
    gst_rate: string | null }[];
  document: { fileName: string; sha256: string; bytes: number };
};

const CHANNELS = ['PORTAL', 'PDF_OCR', 'E_INVOICE', 'EDI'];

/** AP clerk capture (supplier taken from the PO) or supplier portal submission (supplier omitted; the API uses the signed-in supplier). */
export function CaptureInvoiceDialog({ supplierMode = false, onClose, onCaptured }: {
  supplierMode?: boolean; onClose: () => void; onCaptured?: (invoice: { id: string; number: string; status: string }) => void;
}) {
  const pos = useList<PoRow>('/purchase-orders?status=TRANSMITTED,CONFIRMED,PARTIALLY_RECEIVED,RECEIVED,INVOICED');
  const [poNumber, setPoNumber] = useState('');
  const po = useApi<PoDetail>(poNumber ? `/purchase-orders/${encodeURIComponent(poNumber)}` : null);
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [invoiceNo, setInvoiceNo] = useState('');
  const [invoiceDate, setInvoiceDate] = useState(today());
  const [channel, setChannel] = useState(supplierMode ? 'PORTAL' : 'PDF_OCR');
  const [irn, setIrn] = useState('');
  const [signedQr, setSignedQr] = useState('');
  const [extracted, setExtracted] = useState<Extracted | null>(null);

  // Prefill lines from the chosen PO: open quantity (accepted − invoiced for goods, ordered − invoiced otherwise) at PO price,
  // overlaid with what was read from the invoice document for the same PO line.
  const [prefilledFor, setPrefilledFor] = useState('');
  if (po.data && po.data.number === poNumber && prefilledFor !== poNumber) {
    setPrefilledFor(poNumber);
    const read = extracted?.lines.filter((x) => !x.po || x.po === poNumber) ?? [];
    setLines(po.data.lines.map((l) => {
      const goods = l.gr_required && !l.ses_required;
      const open = goods ? minus(l.accepted_qty, l.invoiced_qty) : minus(l.qty, l.invoiced_qty);
      const base = { include: Number(open) > 0, line: l, qty: open === '0' ? minus(l.qty, l.invoiced_qty) : open,
        unit_price: (l.unit_price_minor / 100).toFixed(2), gst_rate: l.gst_rate ?? '', hsn: l.hsn_code ?? '' };
      if (!read.length) return base;
      const doc = read.find((x) => Number(x.po_line) === l.line_no);
      if (!doc) return { ...base, include: false };
      return { ...base, include: true, qty: doc.qty ?? base.qty, unit_price: doc.unit_price ?? base.unit_price,
        gst_rate: doc.gst_rate ?? base.gst_rate, hsn: doc.hsn ?? base.hsn };
    }));
  }

  // Read an invoice PDF/image with the document-capture engine and prefill the form; the clerk still reviews every field.
  const scan = useCommand((file: File) => {
    const form = new FormData();
    form.append('file', file);
    return api.upload<Extracted>('/invoices/documents', form);
  }, {
    success: (r) => `Read ${r.document.fileName}: ${r.lines.length} line${r.lines.length === 1 ? '' : 's'}. Check every field before capture.`,
    onSuccess: (r) => {
      setExtracted(r);
      if (r.header.supplierInvoiceNo) setInvoiceNo(r.header.supplierInvoiceNo);
      if (r.header.invoiceDate) setInvoiceDate(r.header.invoiceDate);
      if (r.header.irn) setIrn(r.header.irn);
      const poRef = r.header.poNumber ?? r.lines.find((l) => l.po)?.po;
      if (poRef && poRef !== poNumber) { setPoNumber(poRef); setLines([]); }
      setPrefilledFor('');
    },
  });

  const chosen = lines.filter((l) => l.include);
  const net = chosen.reduce((s, l) => s + (isNumber(l.qty) && isNumber(l.unit_price) ? Number(l.qty) * rupeesToMinor(l.unit_price) : 0), 0);
  const tax = chosen.reduce((s, l) => s + (isNumber(l.qty) && isNumber(l.unit_price) && isNumber(l.gst_rate)
    ? Math.round(Number(l.qty) * rupeesToMinor(l.unit_price) * Number(l.gst_rate) / 100) : 0), 0);
  const problems = [
    !poNumber && 'Choose a purchase order',
    !invoiceNo.trim() && 'Enter the supplier invoice number',
    !invoiceDate && 'Enter the invoice date',
    channel === 'E_INVOICE' && !irn.trim() && 'An e-invoice needs its IRN',
    poNumber && !chosen.length && 'Include at least one line',
    chosen.some((l) => !isPositive(l.qty) || !isPositive(l.unit_price) || !isNumber(l.gst_rate)) && 'Every included line needs a quantity, unit price and GST rate',
  ].filter(Boolean) as string[];

  const capture = useCommand(() => api.post<{ id: string; number: string; status: string }>('/invoices', {
    supplier: supplierMode ? undefined : po.data?.supplier.code,
    supplier_invoice_no: invoiceNo.trim(), invoice_date: invoiceDate, channel, irn: irn.trim() || undefined,
    signed_qr: channel === 'E_INVOICE' && signedQr.trim() ? signedQr.trim() : undefined,
    lines: chosen.map((l) => ({ po: poNumber, po_line: l.line.line_no, qty: l.qty, unit_price: l.unit_price, gst_rate: l.gst_rate,
      hsn: l.hsn || undefined })),
  }), {
    success: (r) => `Invoice ${r.number} ${supplierMode ? 'submitted' : 'captured'} · ${r.status.replace(/_/g, ' ').toLowerCase()}`,
    onSuccess: (r) => { onCaptured?.(r); onClose(); },
  });

  const update = (i: number, patch: Partial<DraftLine>) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  return (
    <Dialog open title={supplierMode ? 'Submit invoice' : 'Capture invoice'} onClose={onClose}>
      {!supplierMode && (
        <div className="mb-4 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
          <Field label="Read from invoice document (PDF, PNG, JPEG or TIFF, up to 10 MB)"
            hint="The document-capture engine prefills the form. Nothing is stored; review every field before capture.">
            {(id) => (
              <input id={id} type="file" accept="application/pdf,image/png,image/jpeg,image/tiff" disabled={scan.isPending}
                className="block w-full text-sm text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-slate-200 file:px-3 file:py-1.5 file:text-sm"
                onChange={(e) => { const file = e.target.files?.[0]; if (file) { setChannel('PDF_OCR'); scan.mutate(file); } e.target.value = ''; }} />
            )}
          </Field>
          {scan.isPending && <Loading text="Reading the document…" />}
          {extracted && (
            <p className="mt-2 text-xs text-slate-600" role="status">
              Read {extracted.document.fileName}
              {extracted.supplier ? ` · supplier ${extracted.supplier.code} (${extracted.supplier.name})`
                : extracted.header.supplierGstin ? ` · GSTIN ${extracted.header.supplierGstin} not found among suppliers` : ''}
              {extracted.header.grossMinor != null ? ` · document total ${inr(extracted.header.grossMinor)}` : ''}
              {po.data && extracted.supplier && extracted.supplier.code !== po.data.supplier.code ? ' · the document supplier differs from the PO supplier' : ''}
            </p>
          )}
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Purchase order">
          {(id) => (
            <Select id={id} value={poNumber} onChange={(e) => { setPoNumber(e.target.value); setLines([]); setPrefilledFor(''); }}
              options={[{ value: '', label: pos.isLoading ? 'Loading…' : 'Choose a PO' },
                ...pos.items.map((p) => ({ value: p.number, label: `${p.number} · ${p.supplier_code} · ${p.status.replace(/_/g, ' ').toLowerCase()} · ${inr(p.total_minor)}` }))]} />
          )}
        </Field>
        <Field label="Supplier">
          {(id) => <Input id={id} readOnly value={supplierMode ? 'Your company (signed-in supplier)' : po.data ? `${po.data.supplier.code} · ${po.data.supplier.name}` : '–'} />}
        </Field>
        <Field label="Supplier invoice number">
          {(id) => <Input id={id} required value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} placeholder="e.g. INV-TF-8813" />}
        </Field>
        <Field label="Invoice date">
          {(id) => <Input id={id} type="date" required value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />}
        </Field>
        <Field label="Channel">
          {(id) => <Select id={id} value={channel} onChange={(e) => setChannel(e.target.value)} options={CHANNELS.map((c) => ({ value: c, label: c.replace(/_/g, ' ') }))} />}
        </Field>
        <Field label={channel === 'E_INVOICE' ? 'IRN (required for e-invoice)' : 'IRN (optional)'} hint="Validated against the supplier GSTIN, fiscal year and invoice number">
          {(id) => <Input id={id} value={irn} onChange={(e) => setIrn(e.target.value)} />}
        </Field>
        {channel === 'E_INVOICE' && (
          <div className="md:col-span-2">
            <Field label="Signed QR code (optional)" hint="The e-invoice QR (JWT). Its IRN, seller GSTIN, document number and total are checked; at the IRP when configured.">
              {(id) => <Input id={id} value={signedQr} onChange={(e) => setSignedQr(e.target.value)} className="font-mono text-xs" />}
            </Field>
          </div>
        )}
      </div>

      <div className="mt-4">
        {pos.error && <ProblemBox error={pos.error} />}
        {po.error && <ProblemBox error={po.error} />}
        {poNumber && po.isLoading && <Loading text="Loading PO lines…" />}
        {po.data && !lines.length && <Empty title="This PO has no lines" />}
        {lines.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-2 py-2">Bill</th><th className="px-2 py-2">PO line</th><th className="px-2 py-2">Qty</th>
                  <th className="px-2 py-2">Unit price (₹)</th><th className="px-2 py-2">GST %</th><th className="px-2 py-2">HSN/SAC</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {lines.map((l, i) => (
                  <tr key={l.line.id} className="align-top">
                    <td className="px-2 py-2">
                      <input type="checkbox" checked={l.include} onChange={(e) => update(i, { include: e.target.checked })}
                        aria-label={`Include PO line ${l.line.line_no}`} className="mt-2 h-4 w-4" />
                    </td>
                    <td className="px-2 py-2">
                      <p className="font-medium">{l.line.line_no} · {l.line.description}</p>
                      <p className="text-xs text-slate-500">
                        Ordered {qty(l.line.qty, l.line.uom)} · accepted {qty(l.line.accepted_qty)} · invoiced {qty(l.line.invoiced_qty)} · PO price {inr(l.line.unit_price_minor)}
                      </p>
                    </td>
                    <td className="px-2 py-2"><Input aria-label={`Quantity line ${l.line.line_no}`} value={l.qty} disabled={!l.include} onChange={(e) => update(i, { qty: e.target.value })} className="w-24" /></td>
                    <td className="px-2 py-2"><Input aria-label={`Unit price line ${l.line.line_no}`} value={l.unit_price} disabled={!l.include} onChange={(e) => update(i, { unit_price: e.target.value })} className="w-28" /></td>
                    <td className="px-2 py-2"><Input aria-label={`GST rate line ${l.line.line_no}`} value={l.gst_rate} disabled={!l.include} onChange={(e) => update(i, { gst_rate: e.target.value })} className="w-16" /></td>
                    <td className="px-2 py-2"><Input aria-label={`HSN line ${l.line.line_no}`} value={l.hsn} disabled={!l.include} onChange={(e) => update(i, { hsn: e.target.value })} className="w-28" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {chosen.length > 0 && (
          <p className="mt-2 text-right text-sm text-slate-700">Net {inr(net)} · GST {inr(tax)} · <span className="font-semibold">Gross {inr(net + tax)}</span></p>
        )}
      </div>

      <p className="mt-3 text-xs text-slate-500">
        On capture the invoice is duplicate-checked and matched (2-way, 3-way against received quantity, 4-way against inspection-accepted quantity for quality-managed lines, or against approved service entries).
        Differences outside tolerance raise exceptions and a payment block.
      </p>
      {problems.length > 0 && (poNumber || invoiceNo) && <p className="mt-2 text-xs text-amber-700" role="status">{problems[0]}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={problems.length > 0} busy={capture.isPending} onClick={() => capture.mutate()}>
          {supplierMode ? 'Submit invoice' : 'Capture invoice'}
        </Button>
      </div>
    </Dialog>
  );
}

export function MatchChip({ inv }: { inv: Pick<InvoiceRow, 'match_type' | 'first_pass_matched'> }) {
  return (
    <span className="whitespace-nowrap text-xs">
      {inv.match_type ?? '–'}
      {inv.first_pass_matched === true && <span className="ml-1 text-emerald-700">· first pass</span>}
      {inv.first_pass_matched === false && <span className="ml-1 text-amber-700">· after exception</span>}
    </span>
  );
}

export function BlockChip({ blocked }: { blocked: boolean | null | undefined }) {
  if (blocked === null || blocked === undefined) return <span>–</span>;
  return blocked ? <StatusChip status="BLOCKED" /> : <span className="text-xs text-slate-600">Free</span>;
}
