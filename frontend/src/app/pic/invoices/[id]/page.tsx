'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, LinkButton, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import type { ApiError } from '@/lib/pic/api';
import { BlockChip, hasRole, MatchChip, useSessionUser } from '../_components';
import { EInvoiceBadge, EInvoicePanel } from '../_ops';
import { DebitNotesPanel, EarlyPaymentPanel, ScfBadge } from '../_p2p';
import { ApprovalPanel, approvedText, InvoiceApproval } from '../_approval';

type MatchDetail = { invoicedQty?: string; creditedQty?: string; netQty?: string; poQty?: string; receivedQty?: string; acceptedQty?: string;
  alreadyInvoicedQty?: string; sesApprovedMinor?: number; poPriceMinor?: number; invoicePriceMinor?: number };
type TaxSplit = { supply?: 'INTRA' | 'INTER'; cgst?: number; sgst?: number; igst?: number; declared?: boolean; rcm?: { taxMinor: number } };
type InvLine = { id: string; line_no: number; description: string; qty: string; unit_price_minor: number; net_minor: number; hsn_code: string | null;
  gst_rate: string; tax_minor: number; match_status: string | null; match_detail: MatchDetail | null; tax_split?: TaxSplit };
type InvException = { id: string; invoice_line_id: string | null; type: string; delta: Record<string, string | number>; detail: string;
  suggested_action: string; status: string; resolution: string | null; resolution_note: string | null; ai_ref: string | null; created_at: string };
type CreditNote = { id: string; number: string; supplier_credit_note_no: string; note_date: string; reason: string; net_minor: number; tax_minor: number;
  gross_minor: number; lines: { invoice_line: number; qty: string; unitCreditMinor?: number }[] };
type Payment = { id: string; number: string; amount_minor: number; value_date: string; status: string; run_ref: string | null; currency?: string;
  bank_status?: string; bank_utr?: string | null; return_reason?: string | null; tds_minor?: number; tds_base_minor?: number; tds_rate?: string | number | null;
  tds_certificate?: string | null; tds_cert_base_minor?: number; tcs_minor?: number; fx_rate?: string | number | null; amount_group_minor?: number | null;
  fx_gain_loss_minor?: number | null; reversal_doc?: string | null };
type Invoice = { id: string; number: string; supplier_invoice_no: string; fiscal_year: string; company_code: string; invoice_date: string; channel: string;
  irn: string | null; irn_valid: boolean | null; net_minor: number; tax_minor: number; gross_minor: number; status: string; match_type: string | null;
  first_pass_matched: boolean | null; payment_block: boolean | null; due_date: string | null; erp_doc_no: string | null; posting_key: string | null;
  posted_at: string | null; payment_status: string | null; rule_set_version: string | null; duplicate_of: string | null;
  retention_minor?: number; payment_option?: string; discount_minor?: number; currency?: string; msme_capped?: boolean; acceptance_date?: string | null;
  tds_section?: string | null; tds_rate?: string | number | null; tds_base_minor?: number; withholding_tax_minor?: number; fx_rate?: string | number | null;
  gross_group_minor?: number | null; posting_date?: string | null;
  place_of_supply?: string | null; cgst_minor?: number; sgst_minor?: number; igst_minor?: number; reverse_charge?: boolean; rcm_tax_minor?: number;
  tcs_section?: string | null; tcs_rate?: string | number | null; tcs_minor?: number;
  supplier: { id: string; code: string; name: string }; lines: InvLine[]; exceptions: InvException[]; creditNotes: CreditNote[]; payments: Payment[]; debitNotes?: { id: string }[];
  approval?: InvoiceApproval };
type PostResult = { status: string; erpDocument?: string | null; replayed?: boolean; integrationStatus?: string; attempts?: number; error?: string | null };

const RESOLUTIONS = [
  { value: 'CREDIT_NOTE_RECEIVED', label: 'Credit note received' },
  { value: 'PRICE_ACCEPTED', label: 'Price variance accepted' },
  { value: 'GR_POSTED', label: 'Goods receipt now posted' },
  { value: 'NOT_DUPLICATE', label: 'Not a duplicate' },
  { value: 'DISPUTE', label: 'Dispute with supplier' },
  { value: 'CLARIFIED', label: 'Clarified with the approver (approve again)' },
];
const DEFAULT_RESOLUTION: Record<string, string> = { QUANTITY: 'CREDIT_NOTE_RECEIVED', PRICE: 'PRICE_ACCEPTED', MISSING_GR: 'GR_POSTED', DUPLICATE: 'NOT_DUPLICATE',
  APPROVAL: 'CLARIFIED' };
// Which resolution closes which exception type (DMN-03, mirrors payables.RESOLUTIONS).
const ALLOWED: Record<string, string[]> = {
  DUPLICATE: ['NOT_DUPLICATE', 'DISPUTE'],
  PRICE: ['CREDIT_NOTE_RECEIVED', 'PRICE_ACCEPTED', 'DISPUTE'],
  // An approver of the value-band chain refused the invoice (rule INVOICE-APPROVAL).
  APPROVAL: ['CLARIFIED', 'CREDIT_NOTE_RECEIVED', 'DISPUTE'],
};
const DEFAULT_ALLOWED = ['CREDIT_NOTE_RECEIVED', 'GR_POSTED', 'DISPUTE'];
const PENDING_RESOLUTIONS = ['DISPUTE', 'PRICE_APPROVAL_PENDING', 'PRICE_REJECTED'];

function creditLine(l: { invoice_line: number; qty: string; unitCreditMinor?: number }) {
  return l.unitCreditMinor ? `line ${l.invoice_line}: ${qty(l.qty)} × ${inr(l.unitCreditMinor)} price credit` : `line ${l.invoice_line}: ${qty(l.qty)}`;
}

function irnText(inv: Invoice) {
  if (!inv.irn) return inv.channel === 'E_INVOICE' ? 'missing' : 'not applicable';
  return inv.irn_valid === true ? 'valid' : inv.irn_valid === false ? 'INVALID' : 'not checked';
}

const heads = (h: { cgst?: number; sgst?: number; igst?: number }) =>
  [h.cgst ? `CGST ${inr(h.cgst)}` : '', h.sgst ? `SGST ${inr(h.sgst)}` : '', h.igst ? `IGST ${inr(h.igst)}` : ''].filter(Boolean).join(' · ') || 'no tax';

/** Whether finance may lift the payment block of this invoice: posted, unpaid, blocked, and nothing (exception, duplicate hold) explains the block. */
function releasable(inv: Invoice, openExceptions: number) {
  return inv.status === 'POSTED' && inv.payment_status === 'UNPAID' && inv.payment_block === true && !inv.duplicate_of && openExceptions === 0;
}

function deltaText(delta: Record<string, string | number>) {
  if (!delta || !Object.keys(delta).length) return '–';
  return Object.entries(delta).map(([k, v]) => k.endsWith('Minor') ? `${k.replace(/Minor$/, '')} ${inr(Number(v))}` : `${k} ${v}`).join(', ');
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const ref = encodeURIComponent(decodeURIComponent(id));
  const user = useSessionUser();
  const { data: inv, isLoading, error } = useApi<Invoice>(`/invoices/${ref}`);
  const [resolving, setResolving] = useState<InvException | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [posted, setPosted] = useState<(PostResult & { key: string }) | null>(null);

  const ap = hasRole(user, 'AP_CLERK');
  const finance = hasRole(user, 'FINANCE_CONTROLLER');
  const approver = hasRole(user, 'AP_CLERK', 'FINANCE_CONTROLLER');
  const postingKey = inv && user ? `${user.tenant}|${inv.company_code}|${inv.supplier.code}|${inv.supplier_invoice_no}` : '';

  const rematch = useCommand(() => api.post<{ status: string; exceptions: unknown[] }>(`/invoices/${inv!.id}/match`), {
    success: (r) => `Matched again · ${r.status.toLowerCase()}${r.exceptions.length ? ` · ${r.exceptions.length} exception(s)` : ''}`,
  });
  const approve = useCommand(() => api.post<{ status: string; approval?: InvoiceApproval }>(`/invoices/${inv!.id}/approve`), { success: approvedText });
  const post = useCommand(() => api.post<PostResult>(`/invoices/${inv!.id}/post`, {}, { idempotencyKey: postingKey }), {
    success: (r) => r.erpDocument ? `ERP document ${r.erpDocument}${r.replayed ? ' (replayed)' : ''}` : `Posting ${r.status.toLowerCase()}`,
    onSuccess: (r) => setPosted({ ...r, key: postingKey }),
  });

  const lineNo = (lineId: string | null) => inv?.lines.find((l) => l.id === lineId)?.line_no;
  const openExceptions = inv?.exceptions.filter((e) => e.status === 'OPEN') ?? [];
  const duplicateHold = openExceptions.some((e) => e.type === 'DUPLICATE');
  const inApproval = inv?.status === 'MATCHED' && inv.approval?.status === 'PENDING';
  const certPayment = inv?.payments.find((p) => p.tds_certificate && p.status !== 'CANCELLED') ?? inv?.payments.find((p) => p.tds_certificate);

  if (error && (error as ApiError).status === 404) {
    return (
      <Card>
        <Empty title="Invoice not found" hint="It does not exist, or it belongs to a company code or plant outside your access." />
        <div className="mt-4 text-center"><LinkButton href="/pic/invoices">Back to the invoice worklist</LinkButton></div>
      </Card>
    );
  }

  return (
    <>
      <ObjectPage
        type="INVOICE" docRef={inv?.number ?? ''} eyebrow="INV-04 · Invoice" loading={isLoading} error={error}
        title={<>{inv?.number} <span className="text-base font-normal text-slate-500">{inv?.supplier.name}</span></>}
        status={inv?.status}
        actions={inv && (
          <>
            {ap && inv.status === 'EXCEPTION' && !duplicateHold && (
              <Button busy={rematch.isPending} onClick={() => rematch.mutate()}>Re-run match</Button>
            )}
            {ap && ['CAPTURED', 'EXCEPTION'].includes(inv.status) && (
              <Button variant="danger" onClick={() => setRejecting(true)}>Reject invoice</Button>
            )}
            {approver && inv.status === 'MATCHED' && !inApproval && <Button variant="primary" busy={approve.isPending} onClick={() => approve.mutate()}>Approve</Button>}
            {ap && inv.status === 'APPROVED' && <Button variant="primary" busy={post.isPending} disabled={!postingKey} onClick={() => post.mutate()}>Post to ERP</Button>}
            {finance && releasable(inv, openExceptions.length) && <Button onClick={() => setReleasing(true)}>Release payment block</Button>}
            {ap && ['POSTED', 'PAID'].includes(inv.status) && (
              <Button busy={post.isPending} disabled={!postingKey} onClick={() => post.mutate()}>Retry post (idempotent)</Button>
            )}
          </>
        )}
        facts={inv && (
          <div className="space-y-4">
            {posted && (
              <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
                <p className="font-semibold">
                  {posted.erpDocument ? <>ERP document {posted.erpDocument}</> : <>Posting {label(posted.status)}</>}
                  {' · '}status {label(posted.status)} · {posted.replayed ? 'replayed (no second posting)' : 'first posting'}
                </p>
                {posted.integrationStatus && <p>Integration {label(posted.integrationStatus)} after {posted.attempts} attempt(s){posted.error ? ` — ${posted.error}` : ''}</p>}
                <p className="mt-1 text-xs">
                  Posted with Idempotency-Key <span className="font-mono">{posted.key}</span>. Retrying with the same key returns this same ERP
                  document instead of posting the invoice twice.
                </p>
              </div>
            )}
            <Facts items={[
              ['Supplier', `${inv.supplier.code} · ${inv.supplier.name}`], ['Supplier invoice no.', inv.supplier_invoice_no],
              ['Invoice date', date(inv.invoice_date)], ['Channel', label(inv.channel)],
              ['IRN', inv.irn ? <EInvoiceBadge key="irn" invoiceRef={ref} /> : <span key="irn">{irnText(inv)}</span>],
              ['Net', inr(inv.net_minor)], ['Tax (GST)', inr(inv.tax_minor)], ['Gross', inr(inv.gross_minor)],
              ...(inv.place_of_supply ? [
                ['Place of supply', `State code ${inv.place_of_supply}`] as [string, string],
                ['GST heads', heads({ cgst: inv.cgst_minor, sgst: inv.sgst_minor, igst: inv.igst_minor })] as [string, string],
              ] : []),
              ...(inv.reverse_charge ? [['Reverse charge', `Yes: the supplier charges no GST; ${inr(inv.rcm_tax_minor ?? 0)} is self-assessed by the buyer`] as [string, string]] : []),
              ...(inv.tcs_section && inv.tcs_minor ? [['TCS', `${inv.tcs_section} · ${inv.tcs_rate}% = ${inr(inv.tcs_minor)} collected by the supplier, paid with the invoice`] as [string, string]] : []),
              ...(inv.retention_minor ? [
                ['Retention withheld', inr(inv.retention_minor)] as [string, string],
                ['Payable now', inr(inv.gross_minor - inv.creditNotes.reduce((sum, n) => sum + n.gross_minor, 0) - inv.retention_minor)] as [string, string],
              ] : []),
              ...(inv.match_type === 'RETENTION' ? [['Document', 'Retention release (no GST: charged on the original invoices)'] as [string, string]] : []),
              ['Match type', <MatchChip key="m" inv={inv} />],
              ['First-pass match', inv.first_pass_matched === null ? 'not matched yet' : inv.first_pass_matched ? 'yes' : 'no'],
              ['Payment block', <BlockChip key="b" blocked={inv.payment_block} />], ['Due date', date(inv.due_date)],
              ['ERP document', inv.erp_doc_no ?? 'not posted yet'], ['Payment status', inv.payment_status ? <StatusChip key="p" status={inv.payment_status} /> : '–'],
              ['Company code / FY', `${inv.company_code} · ${inv.fiscal_year}`], ['Rules', inv.rule_set_version ?? '–'],
              ['Payment option', <ScfBadge key="po" option={inv.payment_option} />],
              ...(inv.discount_minor ? [['Early-payment discount', inr(inv.discount_minor)] as [string, string]] : []),
              ...(inv.msme_capped ? [['MSME due date', `45 days from acceptance on ${date(inv.acceptance_date)} (MSMED Act s.15)`] as [string, string]] : []),
              ...(inv.tds_section ? [['TDS', `${inv.tds_section} · ${inv.tds_rate}% on ${inr(inv.tds_base_minor ?? 0)} = ${inr(inv.withholding_tax_minor ?? 0)}`] as [string, string]] : []),
              ...(inv.currency && inv.currency !== 'INR' ? [['Currency', `${inv.currency}${inv.fx_rate ? ` · rate ${inv.fx_rate} · ${inr(inv.gross_group_minor ?? 0)} in company currency` : ' · rate fixed at posting'}`] as [string, string]] : []),
              ...(inv.posting_date ? [['Posting date', date(inv.posting_date)] as [string, string]] : []),
            ]} />
            {inv.approval && <ApprovalPanel invoiceId={inv.id} approval={inv.approval} />}
            {inApproval && (
              <p className="text-sm text-amber-800">In approval: {inv.approval?.requiredChain.map((r) => label(r)).join(' → ')}. It can be posted once the last approver has approved.</p>
            )}
            {inv.irn && <p className="break-all font-mono text-[11px] text-slate-500">IRN {inv.irn}</p>}
            {inv.irn_valid === false && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
                The IRN failed validation (see the E-invoice tab). The invoice is held with a tax exception until the supplier sends a valid e-invoice or the exception is resolved.
              </p>
            )}
            {certPayment && <CertificateUse supplier={inv.supplier.code} payment={certPayment} />}
            {inv.payment_block && releasable(inv, openExceptions.length) && (
              <p className="text-sm text-amber-800">
                Payment block: posted and unpaid, and no exception or duplicate hold explains it (for example a block that came with the ERP load).
                {finance ? ' You can release it with an audited reason.' : ' Finance releases it with an audited reason.'}
              </p>
            )}
            {inv.duplicate_of && <p className="text-sm text-amber-800">Suspected duplicate of {inv.duplicate_of}</p>}
            {duplicateHold && (
              <p className="text-sm text-amber-800">Held as a possible duplicate: resolve the hold as &ldquo;not a duplicate&rdquo; or reject the invoice. Re-running the match does not release it.</p>
            )}
            {inv.payment_status === 'IN_PAYMENT' && (
              <p className="text-sm text-amber-800">Paid in a payment run and waiting for the ERP to post the payment (clearing). The invoice is marked paid and reconciled once it does.</p>
            )}
            {inv.status === 'APPROVED' && ap && (
              <p className="text-xs text-slate-500">Posting key: <span className="font-mono">{postingKey}</span> — tenant | company code | supplier | invoice number.</p>
            )}
          </div>
        )}
        lines={inv && (
          <DataTable<InvLine> rows={inv.lines} columns={[
            { key: 'line_no', header: 'Line' },
            { key: 'description', header: 'Item', render: (l) => <><p>{l.description}</p><p className="text-xs text-slate-500">HSN {l.hsn_code ?? '–'} · GST {l.gst_rate}%</p></> },
            { key: 'invoiced', header: 'Invoiced', align: 'right', render: (l) => qty(l.match_detail?.invoicedQty ?? l.qty) },
            { key: 'credited', header: 'Credited', align: 'right', render: (l) => qty(l.match_detail?.creditedQty) },
            { key: 'net', header: 'Net qty', align: 'right', render: (l) => qty(l.match_detail?.netQty) },
            { key: 'accepted', header: 'Accepted', align: 'right', render: (l) => l.match_detail?.sesApprovedMinor !== undefined
              ? <span title="Approved service entries">{inr(l.match_detail.sesApprovedMinor)} SES</span> : qty(l.match_detail?.acceptedQty) },
            { key: 'already', header: 'Already invoiced', align: 'right', render: (l) => qty(l.match_detail?.alreadyInvoicedQty) },
            { key: 'price', header: 'PO vs invoice price', align: 'right', render: (l) => {
              const po = l.match_detail?.poPriceMinor; const iv = l.match_detail?.invoicePriceMinor ?? l.unit_price_minor;
              return <span className={po !== undefined && po !== iv ? 'font-semibold text-amber-700' : ''}>{po !== undefined ? inr(po) : '–'} / {inr(iv)}</span>;
            } },
            { key: 'net_minor', header: 'Net value', align: 'right', render: (l) => inr(l.net_minor) },
            { key: 'tax_minor', header: 'GST', align: 'right', render: (l) => (
              <><p>{inr(l.tax_minor)}</p>{l.tax_split && (l.tax_split.cgst || l.tax_split.sgst || l.tax_split.igst) ? (
                <p className="text-xs text-slate-500" title={l.tax_split.declared ? 'Tax heads as printed on the supplier invoice' : 'Tax heads derived from the place of supply'}>
                  {heads(l.tax_split)}{l.tax_split.declared ? '' : ' (derived)'}</p>
              ) : null}{l.tax_split?.rcm ? <p className="text-xs text-slate-500">reverse charge {inr(l.tax_split.rcm.taxMinor)}</p> : null}</>
            ) },
            { key: 'match_status', header: 'Match', render: (l) => <StatusChip status={l.match_status ?? 'PENDING'} /> },
          ]} />
        )}
        extraTabs={inv ? [
          ...(inv.irn ? [{ id: 'einvoice', label: 'E-invoice', content: <EInvoicePanel invoiceRef={ref} canVerify={ap} /> }] : []),
          { id: 'exceptions', label: `Exceptions (${openExceptions.length} open)`, content: (
            inv.exceptions.length ? (
              <div className="space-y-3">
                {inv.exceptions.map((e) => (
                  <div key={e.id} className={`rounded-lg border p-4 ${e.status === 'OPEN' ? 'border-amber-300 bg-amber-50/50' : 'border-slate-200'}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-slate-900 px-2 py-0.5 font-mono text-xs text-white">{e.type}</span>
                        {lineNo(e.invoice_line_id) && <span className="text-xs text-slate-600">line {lineNo(e.invoice_line_id)}</span>}
                        <StatusChip status={e.status} />
                      </div>
                      {ap && e.status === 'OPEN' && <Button variant="primary" onClick={() => setResolving(e)}>Resolve</Button>}
                    </div>
                    <p className="mt-2 text-sm">{e.detail}</p>
                    <p className="mt-1 text-sm text-slate-700"><span className="text-xs font-semibold uppercase text-slate-500">Delta</span> {deltaText(e.delta)}</p>
                    <p className="mt-1 text-sm text-slate-700"><span className="text-xs font-semibold uppercase text-slate-500">Suggested</span> {e.suggested_action}</p>
                    {e.resolution && (
                      <p className={`mt-1 text-sm ${e.status === 'OPEN' && PENDING_RESOLUTIONS.includes(e.resolution) ? 'text-amber-800' : 'text-emerald-800'}`}>
                        {e.status === 'OPEN' ? 'Pending' : 'Resolved'}: {e.resolution === 'PRICE_APPROVAL_PENDING' ? 'price acceptance waiting for a buyer' : label(e.resolution)}
                        {e.resolution_note ? ` — ${e.resolution_note}` : ''}
                      </p>
                    )}
                    <p className="mt-1 font-mono text-[11px] text-slate-400">{[e.ai_ref, dateTime(e.created_at)].filter(Boolean).join(' · ')}</p>
                  </div>
                ))}
              </div>
            ) : <Empty title="No exceptions" hint="All lines matched within tolerance." />
          ) },
          { id: 'credit-notes', label: `Credit notes (${inv.creditNotes.length})`, content: (
            <DataTable<CreditNote> rows={inv.creditNotes} empty="No credit notes" columns={[
              { key: 'number', header: 'Credit note' },
              { key: 'note_date', header: 'Date', render: (n) => date(n.note_date) },
              { key: 'reason', header: 'Reason' },
              { key: 'lines', header: 'Lines', render: (n) => n.lines.map(creditLine).join(', ') },
              { key: 'net_minor', header: 'Net', align: 'right', render: (n) => inr(n.net_minor) },
              { key: 'tax_minor', header: 'Tax', align: 'right', render: (n) => inr(n.tax_minor) },
              { key: 'gross_minor', header: 'Gross', align: 'right', render: (n) => inr(n.gross_minor) },
            ]} />
          ) },
          { id: 'debit-notes', label: `Debit notes (${inv.debitNotes?.length ?? 0})`, content: (
            <DebitNotesPanel invoiceId={inv.id} invoiceStatus={inv.status} canRaise={ap} />
          ) },
          ...(['POSTED', 'PAID'].includes(inv.status) ? [{ id: 'early-payment', label: 'Early payment & SCF', content: <EarlyPaymentPanel invoiceId={inv.id} /> }] : []),
          { id: 'payments', label: `Payments (${inv.payments.length})`, content: (
            <DataTable<Payment> rows={inv.payments} empty="Not paid yet" columns={[
              { key: 'number', header: 'Payment' },
              { key: 'run_ref', header: 'Run', render: (p) => p.run_ref ?? '–' },
              { key: 'value_date', header: 'Value date', render: (p) => date(p.value_date) },
              { key: 'status', header: 'Status', render: (p) => <StatusChip status={p.status} /> },
              { key: 'bank_status', header: 'Bank', render: (p) => p.bank_status ? <span><StatusChip status={p.bank_status} />{p.bank_utr ? <span className="ml-1 font-mono text-xs text-slate-500">{p.bank_utr}</span> : null}{p.return_reason ? <span className="ml-1 text-xs text-slate-500">{p.return_reason}</span> : null}</span> : '–' },
              { key: 'tds_minor', header: 'TDS', align: 'right', render: (p) => p.tds_minor || p.tds_certificate ? (
                <><p>{inr(p.tds_minor ?? 0)}</p>
                  {p.tds_rate ? <p className="text-xs text-slate-500">{p.tds_rate}% on {inr(p.tds_base_minor ?? 0)}</p> : null}
                  {p.tds_certificate ? <p className="text-xs text-slate-500">s.197 {p.tds_certificate}{p.tds_cert_base_minor ? ` on ${inr(p.tds_cert_base_minor)}` : ''}</p> : null}</>
              ) : '–' },
              { key: 'tcs_minor', header: 'TCS', align: 'right', render: (p) => p.tcs_minor ? inr(p.tcs_minor) : '–' },
              { key: 'fx', header: 'Exchange', render: (p) => p.fx_rate ? (
                <span className="text-xs">rate {p.fx_rate} · {inr(p.amount_group_minor ?? 0)}{p.fx_gain_loss_minor ? <span className={p.fx_gain_loss_minor > 0 ? 'text-emerald-700' : 'text-red-700'}>
                  {' '}{p.fx_gain_loss_minor > 0 ? 'gain' : 'loss'} {inr(Math.abs(p.fx_gain_loss_minor))}</span> : null}</span>
              ) : '–' },
              { key: 'amount_minor', header: 'Amount (net of credit notes and TDS, with TCS)', align: 'right', render: (p) => (
                <>{p.currency && p.currency !== 'INR' ? `${p.currency} ${(p.amount_minor / 100).toFixed(2)}` : inr(p.amount_minor)}
                  {p.reversal_doc ? <p className="text-xs font-normal text-amber-800">ERP reversal {p.reversal_doc}</p> : null}</>
              ) },
            ]} />
          ) },
        ] : []}
      />
      {inv && resolving && <ResolveDialog inv={inv} exc={resolving} onClose={() => setResolving(null)} />}
      {inv && rejecting && <RejectDialog inv={inv} onClose={() => setRejecting(false)} />}
      {inv && releasing && <ReleaseBlockDialog inv={inv} onClose={() => setReleasing(false)} />}
    </>
  );
}

function ResolveDialog({ inv, exc, onClose }: { inv: Invoice; exc: InvException; onClose: () => void }) {
  const allowed = ALLOWED[exc.type] ?? DEFAULT_ALLOWED;
  const options = RESOLUTIONS.filter((r) => allowed.includes(r.value));
  const [resolution, setResolution] = useState(allowed.includes(DEFAULT_RESOLUTION[exc.type]) ? DEFAULT_RESOLUTION[exc.type] : allowed[0]);
  const [note, setNote] = useState('');
  const [creditNote, setCreditNote] = useState(inv.creditNotes[0]?.number ?? '');
  const needsNote = resolution === 'CREDIT_NOTE_RECEIVED';
  const resolve = useCommand(() => api.post<{ status: string; dispute?: boolean; priceApproval?: string[] }>(`/invoices/${inv.id}/exceptions/${exc.id}/resolve`, {
    resolution, note: note.trim(), credit_note: needsNote ? creditNote : undefined,
  }), {
    success: (r) => r.dispute ? 'Dispute recorded; the payment block stays'
      : r.priceApproval ? 'Sent to a buyer for price-variance approval; the exception stays open until approved'
        : `Exception resolved · invoice ${r.status.toLowerCase()}`,
    onSuccess: onClose,
  });
  return (
    <Dialog open title={`Resolve ${exc.type.toLowerCase().replace(/_/g, ' ')} exception`} onClose={onClose}>
      <Card className="mb-4">
        <p className="text-sm">{exc.detail}</p>
        <p className="mt-1 text-sm text-slate-600">Suggested: {exc.suggested_action}</p>
      </Card>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Resolution">
          {(id) => <Select id={id} value={resolution} onChange={(e) => setResolution(e.target.value)} options={options} />}
        </Field>
        {needsNote && (
          <Field label="Credit note" hint={inv.creditNotes.length ? undefined : 'No credit note has been received for this invoice yet'}>
            {(id) => (
              <Select id={id} value={creditNote} onChange={(e) => setCreditNote(e.target.value)}
                options={inv.creditNotes.length
                  ? inv.creditNotes.map((n) => ({ value: n.number, label: `${n.number} · ${inr(n.gross_minor)} · ${n.lines.map(creditLine).join(', ')}` }))
                  : [{ value: '', label: 'None received' }]} />
            )}
          </Field>
        )}
        <div className="md:col-span-2">
          <Field label="Note (required)">
            {(id) => <Textarea id={id} required value={note} onChange={(e) => setNote(e.target.value)} placeholder="What was agreed and with whom" />}
          </Field>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        When the last open exception is resolved the invoice is matched again automatically. A dispute keeps the payment block.
        {resolution === 'PRICE_ACCEPTED' && ' Accepting a price variance opens a buyer approval (not the PO creator); the PO price changes only when the buyer approves.'}
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!note.trim() || (needsNote && !creditNote)} busy={resolve.isPending} onClick={() => resolve.mutate()}>Resolve</Button>
      </div>
    </Dialog>
  );
}

function RejectDialog({ inv, onClose }: { inv: Invoice; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const reject = useCommand(() => api.post(`/invoices/${inv.id}/reject`, { reason: reason.trim() }), {
    success: `Invoice ${inv.number} rejected; nothing is posted or paid`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Reject ${inv.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        Rejecting closes the open exceptions and ends the invoice process. Use it for a confirmed duplicate or an invoice the supplier will
        cancel and re-issue.
      </p>
      <div className="mt-3">
        <Field label="Reason (required)">
          {(id) => <Textarea id={id} required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. duplicate of KD/2702-118, confirmed with the supplier" />}
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={reason.trim().length < 3} busy={reject.isPending} onClick={() => reject.mutate()}>Reject invoice</Button>
      </div>
    </Dialog>
  );
}

/** The s.197 certificate a payment of this invoice used, with how much of its amount cap is consumed (from the supplier finance view). */
function CertificateUse({ supplier, payment }: { supplier: string; payment: Payment }) {
  const finance = useApi<{ certificates: { certificateNo: string; ratePct: string; maxBaseMinor: number | null; consumedBaseMinor: number; remainingBaseMinor: number | null; status: string }[] }>(
    `/suppliers/${encodeURIComponent(supplier)}/finance`);
  const cert = finance.data?.certificates.find((c) => c.certificateNo === payment.tds_certificate);
  return (
    <p className="text-sm text-slate-700" aria-label="TDS certificate used">
      TDS certificate <span className="font-mono">{payment.tds_certificate}</span> (s.197) applied on payment {payment.number}
      {payment.tds_cert_base_minor ? `: ${inr(payment.tds_cert_base_minor)} of the base taxed at its rate` : ''}.
      {cert && cert.maxBaseMinor !== null ? ` Cap ${inr(cert.maxBaseMinor)} · consumed ${inr(cert.consumedBaseMinor)} · remaining ${inr(cert.remainingBaseMinor ?? 0)}; beyond the cap the section rate applies.`
        : cert ? ' No amount cap on this certificate.' : ''}
    </p>
  );
}

function ReleaseBlockDialog({ inv, onClose }: { inv: Invoice; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const release = useCommand(() => api.post(`/invoices/${inv.id}/payment-block/release`, { reason: reason.trim() }), {
    success: `Payment block of ${inv.number} released; it is payable in the next run`, onSuccess: onClose,
  });
  return (
    <Dialog open title={`Release payment block · ${inv.number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        Lifts the payment block of this posted, unpaid invoice. Only a block that no exception or duplicate hold explains can be released this way;
        an invoice with open exceptions is released by resolving them, and a blocked supplier is unblocked on the supplier. The release is audited with your reason.
      </p>
      <div className="mt-3">
        <Field label="Reason (at least 5 characters)" required>
          {(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Block came with the ERP load; checked with the buyer, goods accepted" />}
        </Field>
      </div>
      <ProblemBox error={release.error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={reason.trim().length < 5} busy={release.isPending} onClick={() => release.mutate()}>Release payment block</Button>
      </div>
    </Dialog>
  );
}
