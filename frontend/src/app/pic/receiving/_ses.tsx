'use client';

import { ReactNode, useState } from 'react';
import { Button, Dialog, Field, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { useApi, useCommand } from '@/lib/pic/hooks';

// ---------------------------------------------------------------- service entry sheet lifecycle (DRAFT / SUBMITTED / APPROVED / REJECTED / REVOKED)
type SesDetail = { id: string; number: string; status: string; row_version: number; canDecide: boolean };
type SesResult = { number: string; status: string };

const path = (ses: string, action: string) => `/service-entries/${encodeURIComponent(ses)}/${action}`;
const done = (r: SesResult) => `${r.number} ${r.status.replace(/_/g, ' ').toLowerCase()}`;

/** Actions on one sheet by its status: submit / resubmit (supplier, ses:create), approve and reject (the service owner with the open approval
 *  step, read from GET /v1/service-entries/{ref} canDecide) and revoke an approval given in error (service owner). */
export function SesActions({ number, status, canSubmit, canApprove }: { number: string; status: string; canSubmit: boolean; canApprove: boolean }) {
  // Only a SUBMITTED sheet can be decided: ask the API whether this user holds its approval step (role, four-eyes, delegation).
  const detail = useApi<SesDetail>(canApprove && status === 'SUBMITTED' ? `/service-entries/${encodeURIComponent(number)}` : null);
  const [dialog, setDialog] = useState<'reject' | 'revoke' | null>(null);
  const submit = useCommand(() => api.post<SesResult>(path(number, 'submit')), { success: done });
  const approve = useCommand(() => api.post<SesResult>(path(number, 'approve')), { success: done });
  const buttons: ReactNode[] = [];
  if (canSubmit && (status === 'DRAFT' || status === 'REJECTED')) {
    buttons.push(<Button key="submit" variant="primary" busy={submit.isPending} onClick={() => submit.mutate()}>{status === 'DRAFT' ? 'Submit' : 'Resubmit'}</Button>);
  }
  if (canApprove && status === 'SUBMITTED' && detail.data?.canDecide) {
    buttons.push(<Button key="approve" variant="primary" busy={approve.isPending} onClick={() => approve.mutate()}>Approve</Button>);
    buttons.push(<Button key="reject" onClick={() => setDialog('reject')}>Reject</Button>);
  }
  if (canApprove && status === 'APPROVED') {
    buttons.push(<Button key="revoke" variant="danger" onClick={() => setDialog('revoke')}>Revoke approval</Button>);
  }
  if (!buttons.length && !dialog) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {buttons}
      {dialog && <SesReasonDialog number={number} action={dialog} onClose={() => setDialog(null)} />}
    </div>
  );
}

function SesReasonDialog({ number, action, onClose }: { number: string; action: 'reject' | 'revoke'; onClose: () => void }) {
  const [reason, setReason] = useState('');
  const run = useCommand(() => api.post<SesResult>(path(number, action), { reason: reason.trim() }), { success: done, onSuccess: onClose });
  const min = action === 'revoke' ? 10 : 3;
  return (
    <Dialog open title={`${action === 'reject' ? 'Reject' : 'Revoke approval of'} ${number}`} onClose={onClose}>
      <p className="text-sm text-slate-700">
        {action === 'reject'
          ? 'The supplier sees the reason and can correct and resubmit the sheet.'
          : 'The approved service value leaves the PO line again. Refused while an invoice uses that value (reject or credit the invoice first).'}
      </p>
      <div className="mt-3">
        <Field label={`Reason (at least ${min} characters, audited)`}>
          {(id) => <Textarea id={id} required maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={action === 'revoke' ? 'danger' : 'primary'} disabled={reason.trim().length < min} busy={run.isPending} onClick={() => run.mutate()}>
          {action === 'reject' ? 'Reject sheet' : 'Revoke approval'}
        </Button>
      </div>
    </Dialog>
  );
}
