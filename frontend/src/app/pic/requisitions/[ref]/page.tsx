'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { ObjectPage } from '@/components/pic/object';
import { Button, DataTable, Dialog, Facts, Field, Input, StatusChip } from '@/components/pic/ui';
import { api, Paged } from '@/lib/pic/api';
import { date, dateTime, inr, label, qty, rupeesToMinor } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';
import { AccountAssignment, NEEDS_ACCOUNT, PolicyProblem, PrLine, Requisition, SubmitPanel, useReference } from '../_components';

const EDITABLE = ['DRAFT', 'RETURNED', 'APPROVED'];

export default function RequisitionPage() {
  const { ref } = useParams<{ ref: string }>();
  const { data: pr, isLoading, error } = useApi<Requisition>(`/requisitions/${encodeURIComponent(ref)}`);
  const submittable = !!pr && ['DRAFT', 'RETURNED'].includes(pr.status);
  // The API only lets the requester submit; "mine" tells us whether that is the signed-in user.
  const mine = useApi<Paged<Requisition>>(submittable ? `/requisitions?mine=true&status=${pr.status}&limit=200` : null);
  const isRequester = !!pr && !!mine.data?.items.some((r) => r.id === pr.id);
  const [dialog, setDialog] = useState<'submit' | null>(null);
  const [editing, setEditing] = useState<PrLine | null>(null);
  const canEdit = !!pr && EDITABLE.includes(pr.status);

  const budget = pr?.budget_result;
  return (
    <>
      <ObjectPage
        type="REQUISITION" docRef={pr?.number ?? ref} eyebrow="REQ-02 · Purchase requisition" loading={isLoading} error={error}
        title={<>{pr?.number} <span className="text-base font-normal text-slate-500">{label(pr?.origin)} · plant {pr?.plant}</span></>}
        status={pr?.status}
        actions={submittable && isRequester ? <Button variant="primary" onClick={() => setDialog('submit')}>Submit for approval</Button> : undefined}
        facts={pr && (
          <div className="space-y-4">
            <Facts items={[
              ['Origin', label(pr.origin)], ['Origin reference', pr.origin_ref ?? '–'],
              ['Purpose', <>{pr.purpose_code ?? <span className="text-red-700">missing (P01)</span>}{pr.purpose_text ? <span className="block text-xs font-normal text-slate-600">{pr.purpose_text}</span> : null}</>],
              ['Total', inr(pr.total_minor)],
              ['Budget', label(budget?.outcome ?? (pr.submitted_at ? '' : 'checked on submit'))],
              ['Approval route', pr.approval_chain?.length ? pr.approval_chain.map(label).join(' → ') : pr.submitted_at ? 'auto-approved' : 'determined on submit'],
              ['Submitted', dateTime(pr.submitted_at)], ['Approved', dateTime(pr.approved_at)],
            ]} />
            {(budget?.checks?.length ?? 0) > 0 && (
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Budget check</p>
                <ul className="mt-1 space-y-0.5 text-sm">
                  {budget!.checks!.map((c) => (
                    <li key={c.costObject} className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{c.costObject.replace(':', ' ')}</span>
                      <span>{inr(c.amountMinor)} of {inr(c.availableMinor)} available</span>
                      <span className="text-xs text-slate-500">{label(c.control)} control</span>
                      <StatusChip status={c.result} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {pr.policy_hints?.length ? <p className="text-sm text-amber-800">Policy hints: {pr.policy_hints.join('; ')}</p> : null}
            <p className="text-xs text-slate-500">Rules {pr.rule_set_version ?? 'applied on submit'} · company code {pr.company_code}</p>
          </div>
        )}
        lines={pr && (
          <DataTable<PrLine> rows={pr.lines ?? []} empty="No lines" columns={[
            { key: 'line_no', header: 'Line' },
            { key: 'description', header: 'Item', render: (l) => (
              <div>
                <p className="font-medium">{l.description}</p>
                <p className="text-xs text-slate-500">{label(l.item_type)} · {l.material_group ?? '–'}{l.reusable ? ' · reusable (MDM request started)' : ''}</p>
              </div>
            ) },
            { key: 'purchase_type', header: 'Type', render: (l) => label(l.purchase_type) },
            { key: 'qty', header: 'Quantity', align: 'right', render: (l) => qty(l.qty, l.uom) },
            { key: 'price_est_minor', header: 'Est. price', align: 'right', render: (l) => inr(l.price_est_minor) },
            { key: 'value', header: 'Value', align: 'right', render: (l) => inr(Math.round(Number(l.qty) * l.price_est_minor)) },
            { key: 'account', header: 'Account', render: (l) => l.account_assignment_code ? `${label(l.account_assignment_type)} ${l.account_assignment_code}` : '–' },
            { key: 'need_date', header: 'Need', render: (l) => date(l.need_date) },
            { key: 'quotes_attached', header: 'Quotes', align: 'right', render: (l) => (l.item_type === 'FREE_TEXT' ? l.quotes_attached : '–') },
            { key: 'source', header: 'Source', render: (l) => l.source_determination?.method
              ? <span className="text-xs">{label(l.source_determination.method)}{(l.source_determination.allocations ?? []).map((a) => ` · ${a.supplier}`).join('')}</span> : '–' },
            { key: 'ordered_qty', header: 'Ordered', align: 'right', render: (l) => qty(l.ordered_qty) },
            { key: 'sourcing_status', header: 'Sourcing', render: (l) => l.sourcing_status ? <StatusChip status={l.sourcing_status} /> : '–' },
            ...(canEdit ? [{ key: 'edit', header: '', render: (l: PrLine) => <Button onClick={() => setEditing(l)}>Edit line</Button> }] : []),
          ]} />
        )}
      />
      {pr && dialog === 'submit' && (
        <Dialog open title={`Submit ${pr.number} for approval`} onClose={() => setDialog(null)}>
          <SubmitPanel pr={pr} />
        </Dialog>
      )}
      {pr && editing && <EditLineDialog pr={pr} line={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function EditLineDialog({ pr, line, onClose }: { pr: Requisition; line: PrLine; onClose: () => void }) {
  const ref = useReference();
  const [qtyValue, setQty] = useState(line.qty);
  const [price, setPrice] = useState(String(line.price_est_minor / 100));
  const [aat, setAat] = useState(line.account_assignment_type ?? '');
  const [aac, setAac] = useState(line.account_assignment_code ?? '');
  const [needDate, setNeedDate] = useState(line.need_date);
  const [description, setDescription] = useState(line.description);

  const changes: Record<string, unknown> = {};
  if (qtyValue !== line.qty && Number(qtyValue) !== Number(line.qty)) changes.qty = qtyValue;
  if (rupeesToMinor(price) !== line.price_est_minor) changes.price_est_minor = rupeesToMinor(price);
  if (aat && aat !== line.account_assignment_type) changes.account_assignment_type = aat;
  if (aac && aac !== line.account_assignment_code) changes.account_assignment_code = aac;
  if (needDate !== line.need_date) changes.need_date = needDate;
  if (description.trim() !== line.description) changes.description = description.trim();
  const touchesApproval = 'qty' in changes || 'price_est_minor' in changes || 'account_assignment_code' in changes || 'account_assignment_type' in changes;
  const invalid = !(Number(qtyValue) > 0) || !(Number(price) > 0) || !needDate || !description.trim()
    || (NEEDS_ACCOUNT.includes(line.purchase_type) && (!aat || !aac));

  const save = useCommand(() => api.patch<{ status: string; reapproval: boolean }>(`/requisitions/${pr.number}/lines/${line.line_no}`, changes), {
    success: (r) => r.reapproval ? `Line ${line.line_no} changed — approval restarted (${label(r.status)})` : `Line ${line.line_no} changed — no re-approval needed`,
    onSuccess: onClose,
  });

  return (
    <Dialog open title={`Edit ${pr.number} line ${line.line_no}`} onClose={onClose}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="md:col-span-2"><Field label="Description">{(id) => <Input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field></div>
        <Field label={`Quantity (${line.uom})`}>{(id) => <Input id={id} type="number" min="0" step="any" value={qtyValue} onChange={(e) => setQty(e.target.value)} />}</Field>
        <Field label="Estimated unit price (₹)">{(id) => <Input id={id} type="number" min="0" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} />}</Field>
        <AccountAssignment type={aat} code={aac} costObjects={ref.data?.costObjects ?? []} required={NEEDS_ACCOUNT.includes(line.purchase_type)}
          onChange={(t, c) => { setAat(t); setAac(c); }} />
        <Field label="Need date">{(id) => <Input id={id} type="date" value={needDate} onChange={(e) => setNeedDate(e.target.value)} />}</Field>
      </div>
      <div className={`mt-4 rounded-lg border px-3 py-2 text-sm ${pr.status === 'APPROVED' && touchesApproval ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-slate-200 bg-slate-50 text-slate-700'}`}>
        {pr.status === 'APPROVED'
          ? touchesApproval
            ? 'This changes the line value or account assignment of an approved requisition: approval restarts and the requisition goes back to the approvers (§10.4). Supplier changes restart approval as well.'
            : 'Changes to value, account assignment or supplier restart approval. Need date and description changes keep the approval.'
          : 'The requisition is not approved yet: changes are saved to the draft and checked again on submit. Once approved, value, account or supplier changes restart approval.'}
      </div>
      <div className="mt-3"><PolicyProblem error={save.error} /></div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={save.isPending} disabled={invalid || !Object.keys(changes).length} onClick={() => save.mutate()}>Save change</Button>
      </div>
    </Dialog>
  );
}
