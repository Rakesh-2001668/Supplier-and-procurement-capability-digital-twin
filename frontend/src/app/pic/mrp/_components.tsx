'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Dialog, Field, ProblemBox, Textarea } from '@/components/pic/ui';
import { api } from '@/lib/pic/api';
import { inr, qty } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

export type Me = { user: string; name: string; roles: string[]; scopes: string[]; attributes: Record<string, unknown> };

/** Current principal (roles and scopes) from the API, so actions are only offered to users who may run them. */
export function useMe() {
  const { data } = useApi<Me>('/me');
  return { roles: data?.roles ?? [], scopes: data?.scopes ?? [], me: data };
}

export type Allocation = { qty: string; share: string | number | null; supplier: string; contractId: string | null; priceSource: string; unitPriceMinor: number | null };
export type SourceDetermination = { method?: string; excluded?: unknown[]; allocations?: Allocation[] } | null;

export type PlannedOrder = {
  id: string; number: string; mrp_run_id: string; material_id: string; material?: string; plant: string; storage_location: string | null;
  qty: string; need_date: string; release_date: string; status: string; source: SourceDetermination; exception_codes: string[];
  requisition_id: string | null; created_at: string;
};

export function SourceSummary({ source }: { source: SourceDetermination }) {
  if (!source || !source.method) return <span className="text-slate-500">not determined</span>;
  return (
    <div className="text-xs">
      <span className="font-semibold text-slate-800">{source.method.replace(/_/g, ' ').toLowerCase()}</span>
      {(source.allocations ?? []).map((a, i) => (
        <p key={i} className="text-slate-600">
          {a.supplier} · {qty(a.qty)}{a.share ? ` (${a.share}%)` : ''}{a.unitPriceMinor != null ? ` @ ${inr(a.unitPriceMinor)}` : ''} · {a.priceSource.replace(/_/g, ' ').toLowerCase()}
        </p>
      ))}
    </div>
  );
}

/** A reason for an MRP command (cancel / unfirm a planned order, close an exception); audited with the command. */
export function ReasonDialog({ title, hint, action, danger, onSubmit, onClose }: {
  title: string; hint: string; action: string; danger?: boolean; onSubmit: (reason: string) => Promise<unknown>; onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const run = useCommand(() => onSubmit(reason.trim()), { success: `${action}: done`, onSuccess: onClose });
  return (
    <Dialog open title={title} onClose={onClose}>
      <p className="text-sm text-slate-700">{hint}</p>
      <div className="mt-3"><Field label="Reason *">{(id) => <Textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field></div>
      <div className="mt-3"><ProblemBox error={run.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Back</Button>
        <Button variant={danger ? 'danger' : 'primary'} busy={run.isPending} disabled={reason.trim().length < 3} onClick={() => run.mutate()}>{action}</Button>
      </div>
    </Dialog>
  );
}

/** Firm / unfirm / cancel / convert actions for a planned order (MRP-03). Only CREATED and FIRMED orders can change. */
export function PlannedOrderActions({ order, canPlan }: { order: PlannedOrder; canPlan: boolean }) {
  const [dialog, setDialog] = useState<'cancel' | 'unfirm' | null>(null);
  const firm = useCommand(() => api.post(`/planned-orders/${order.number}/firm`), { success: `${order.number} firmed` });
  const convert = useCommand(() => api.post<{ number: string }>(`/planned-orders/${order.number}/convert`),
    { success: (pr) => `${order.number} converted to requisition ${pr.number}` });
  const open = ['CREATED', 'FIRMED'].includes(order.status);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {canPlan && order.status === 'CREATED' && (
        <Button busy={firm.isPending} disabled={convert.isPending} onClick={() => firm.mutate()}>Firm</Button>
      )}
      {canPlan && open && (
        <Button variant="primary" busy={convert.isPending} disabled={firm.isPending} onClick={() => convert.mutate()}>Convert to PR</Button>
      )}
      {canPlan && order.status === 'FIRMED' && <Button onClick={() => setDialog('unfirm')}>Unfirm</Button>}
      {canPlan && open && <Button variant="danger" onClick={() => setDialog('cancel')}>Cancel</Button>}
      {dialog === 'cancel' && (
        <ReasonDialog title={`Cancel ${order.number}`} action="Cancel planned order" danger onClose={() => setDialog(null)}
          hint="The receipt leaves the plan and the open exception messages about this order are closed with the reason; the next net-change run replans the material."
          onSubmit={(reason) => api.post(`/planned-orders/${order.number}/cancel`, { reason })} />
      )}
      {dialog === 'unfirm' && (
        <ReasonDialog title={`Unfirm ${order.number}`} action="Unfirm" onClose={() => setDialog(null)}
          hint="The order goes back to CREATED: the next MRP run may change or replace it."
          onSubmit={(reason) => api.post(`/planned-orders/${order.number}/unfirm`, { reason })} />
      )}
      {convert.data?.number && (
        <Link href={`/pic/requisitions/${convert.data.number}`} className="text-xs font-medium text-[#1A56DB] hover:underline">{convert.data.number} →</Link>
      )}
      {!convert.data && order.requisition_id && (
        <Link href={`/pic/requisitions/${order.requisition_id}`} className="text-xs font-medium text-[#1A56DB] hover:underline">View requisition →</Link>
      )}
      {!open && !order.requisition_id && <span className="text-xs text-slate-400">–</span>}
    </div>
  );
}
