'use client';

import { useState } from 'react';
import { Button, Dialog, Field, StatusChip, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { dateTime, inr, label } from '@/lib/pic/format';
import { useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- invoice approval chain by value band (rule INVOICE-APPROVAL)
export type ApprovalStep = { taskId: string; sequence: number; role: string; status: string; decision: string | null; decidedBy: string | null;
  decidedAt: string | null; comment: string | null; due: string | null; delegatedBy: string | null };
export type InvoiceApproval = { status: 'NONE' | 'PENDING' | 'APPROVED' | 'REJECTED' | string; requiredChain: string[]; band: { fromMinor?: number } | null;
  rule: string | null; valueMinor: number | null; apApprover?: string | null; steps: ApprovalStep[]; myTaskId?: string | null };

// Acronym roles stay in capitals ('CFO', not 'Cfo'): the last approver of the 1 crore band (rule INVOICE-APPROVAL default bands).
const roleName = (role: string) => (role === 'CFO' || role === 'CPO' ? role : label(role));

/** Toast text after POST /approve: approved for posting, or sent on to the roles of the invoice's value band. */
export function approvedText(result: { status?: string; approval?: InvoiceApproval }): string {
  if (result.status === 'MATCHED' && result.approval?.status === 'PENDING') {
    return `Sent to approval: ${result.approval.requiredChain.map(roleName).join(' → ')}`;
  }
  return result.status === 'APPROVED' ? 'Invoice approved for posting' : `Invoice ${label(result.status ?? '')}`;
}

/** The approval chain: accounts payable first, then the roles of the value band, each with its decision; the caller's own open step can be
 *  decided here (same as the task inbox: delegation, four-eyes, value limit apply). */
export function ApprovalPanel({ invoiceId, approval }: { invoiceId: string; approval: InvoiceApproval }) {
  const [deciding, setDeciding] = useState<'APPROVE' | 'REJECT' | 'RETURN' | null>(null);
  if (approval.status === 'NONE' && !approval.requiredChain.length) return null;
  const band = approval.band?.fromMinor !== undefined ? `value band from ${inr(approval.band.fromMinor)}` : 'value band';
  return (
    <section aria-label="Approval chain" className="rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Approval chain</h3>
          <p className="text-xs text-slate-500">
            {approval.valueMinor !== null ? `${inr(approval.valueMinor)} · ` : ''}{band}{approval.rule ? ` · ${approval.rule}` : ''}
          </p>
        </div>
        <StatusChip status={approval.status === 'NONE' ? 'NOT_STARTED' : approval.status} />
      </div>
      <ol className="mt-3 space-y-2 text-sm">
        <li className="flex flex-wrap items-center gap-2">
          <span className="w-6 text-xs text-slate-500">1</span>
          <span className="font-medium">Accounts payable</span>
          {approval.apApprover ? <span className="text-xs text-slate-600">approved by {approval.apApprover}</span>
            : approval.status === 'APPROVED' ? <StatusChip status="APPROVED" />
              : <span className="text-xs text-slate-500">approves first (Approve button)</span>}
        </li>
        {(approval.steps.length ? approval.steps : approval.requiredChain.map((role, i) => ({
          taskId: `planned-${i}`, sequence: i + 1, role, status: 'PLANNED', decision: null, decidedBy: null, decidedAt: null, comment: null, due: null, delegatedBy: null,
        }))).map((s) => (
          <li key={s.taskId} className="flex flex-wrap items-center gap-2">
            <span className="w-6 text-xs text-slate-500">{s.sequence + 1}</span>
            <span className="font-medium">{roleName(s.role)}</span>
            <StatusChip status={s.decision ?? s.status} />
            {s.decidedBy && <span className="text-xs text-slate-600">{s.decidedBy}{s.decidedAt ? ` · ${dateTime(s.decidedAt)}` : ''}{s.delegatedBy ? ' (delegated authority)' : ''}</span>}
            {s.status === 'OPEN' && s.due && <span className="text-xs text-slate-500">due {dateTime(s.due)}</span>}
            {s.comment && <span className="text-xs text-slate-600">“{s.comment}”</span>}
          </li>
        ))}
      </ol>
      {approval.myTaskId && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => setDeciding('APPROVE')}>Approve</Button>
          <Button onClick={() => setDeciding('RETURN')}>Return</Button>
          <Button variant="danger" onClick={() => setDeciding('REJECT')}>Reject</Button>
        </div>
      )}
      {approval.status === 'REJECTED' && (
        <p className="mt-2 text-xs text-amber-800">An approver refused the invoice: it is back with accounts payable as an APPROVAL exception (clarify and resubmit, dispute, or reject).</p>
      )}
      {deciding && <DecisionDialog invoiceId={invoiceId} decision={deciding} onClose={() => setDeciding(null)} />}
    </section>
  );
}

function DecisionDialog({ invoiceId, decision, onClose }: { invoiceId: string; decision: 'APPROVE' | 'REJECT' | 'RETURN'; onClose: () => void }) {
  const [comment, setComment] = useState('');
  const needsComment = decision !== 'APPROVE';
  const decide = useCommand(() => api.post<{ status: string; approval?: InvoiceApproval }>(`/invoices/${invoiceId}/approval/decision`,
    { decision, comment: comment.trim() || undefined }), {
    success: (r) => r.status === 'APPROVED' ? 'Invoice approved for posting'
      : r.approval?.status === 'PENDING' ? 'Approved; the next approver of the chain is asked' : `Invoice ${label(r.status)}`,
    onSuccess: onClose,
  });
  return (
    <Dialog open title={`${label(decision)} invoice approval`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        {decision === 'APPROVE' ? 'Your approval moves the invoice to the next approver, or to posting after the last one.'
          : 'The invoice goes back to accounts payable as an APPROVAL exception with your comment.'}
      </p>
      <div className="mt-3">
        <Field label={needsComment ? 'Comment (required)' : 'Comment (optional)'}>
          {(id) => <Textarea id={id} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={decision === 'REJECT' ? 'danger' : 'primary'} disabled={needsComment && !comment.trim()} busy={decide.isPending}
          onClick={() => decide.mutate()}>{label(decision)}</Button>
      </div>
    </Dialog>
  );
}
