'use client';

// SoD exception path (item 46). A command refused with 409 SOD_CONFLICT on a rule in MITIGATE mode carries `mitigation`: who may
// approve, how long the exception can last and the compensating control. The user explains why; the approver decides in the task inbox;
// an approved, time-boxed grant lets the same command go through once.

import { useState } from 'react';
import { api, ApiError } from '@/lib/pic/api';
import { label } from '@/lib/pic/format';
import { useCommand } from '@/lib/pic/hooks';
import { Button, Dialog, Field, ProblemBox, Textarea } from './ui';

export type Offer = { available: boolean; ruleCode: string; action: string; refs: Record<string, string>; approverRoles: string[];
  maxValidityHours: number; compensatingControl: string; pendingRequest: string | null };

export function offerOf(error: ApiError | Error | null | undefined): Offer | null {
  const offer = (error as ApiError | undefined)?.problem?.mitigation as Offer | undefined;
  return offer && offer.available ? offer : null;
}

export function MitigationRequest({ offer }: { offer: Offer }) {
  const [open, setOpen] = useState(false);
  const [justification, setJustification] = useState('');
  const send = useCommand(() => api.post('/sod/mitigations', { ruleCode: offer.ruleCode, action: offer.action, refs: offer.refs, justification }), {
    success: 'Exception requested: the approver has been notified', onSuccess: () => setOpen(false),
  });
  if (offer.pendingRequest) return <p className="mt-2 text-xs text-slate-700">An exception request for this is already waiting for {offer.approverRoles.map(label).join(' / ')}.</p>;
  return (
    <div className="mt-2">
      <Button onClick={() => setOpen(true)}>Request an exception ({offer.ruleCode})</Button>
      <Dialog open={open} title={`Segregation-of-duties exception · ${offer.ruleCode}`} onClose={() => setOpen(false)}>
        <dl className="mb-3 space-y-1 text-sm">
          <div><dt className="inline font-semibold">Approved by: </dt><dd className="inline">{offer.approverRoles.map(label).join(' then ')}</dd></div>
          <div><dt className="inline font-semibold">Valid for at most: </dt><dd className="inline">{offer.maxValidityHours} hours, single use unless the rule says otherwise</dd></div>
          <div><dt className="inline font-semibold">Compensating control: </dt><dd className="inline">{offer.compensatingControl || '–'}</dd></div>
        </dl>
        <Field label="Business reason (at least 20 characters)">{(id) => (
          <Textarea id={id} rows={4} value={justification} onChange={(e) => setJustification(e.target.value)} />
        )}</Field>
        <div className="mt-3 flex justify-end">
          <Button variant="primary" busy={send.isPending} disabled={justification.trim().length < 20} onClick={() => send.mutate()}>Send request</Button>
        </div>
        <ProblemBox error={send.error} />
      </Dialog>
    </div>
  );
}
