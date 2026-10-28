'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Button, Field, Input, ProblemBox, Select, StatusChip, Textarea } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { inr, label } from '@/lib/pic/format';
import { useApi, useCommand } from '@/lib/pic/hooks';

export type Reference = {
  plants: { code: string; name: string }[];
  costObjects: { type: string; code: string; name: string }[];
  materials: { number: string; description: string; uom: string; type: string; category: string | null; standardPriceMinor: number | null }[];
  suppliers: { code: string; name: string; status: string }[];
  catalogue: { id: string; description: string; priceMinor: number; uom: string; category: string | null }[];
};

export function useReference() {
  return useApi<Reference>('/reference');
}

export type BudgetCheck = { result: string; control: string; costObject: string; amountMinor: number; availableMinor: number };
export type Allocation = { qty: string; share: string | number | null; supplier: string; contractId: string | null; priceSource: string; unitPriceMinor: number | null };

export type PrLine = {
  id: string; line_no: number; item_type: string; purchase_type: string; material_id: string | null; catalogue_item_id: string | null;
  description: string; material_group: string | null; category: string | null; qty: string; uom: string; price_est_minor: number;
  account_assignment_type: string | null; account_assignment_code: string | null; need_date: string; plant: string;
  quotes_attached: number; reusable: boolean; mdm_request_id: string | null; ordered_qty: string; sourcing_status: string | null;
  source_determination: { method?: string; allocations?: Allocation[] } | null; planned_order_id: string | null;
};

export type Requisition = {
  id: string; number: string; origin: string; origin_ref: string | null; purpose_code: string | null; purpose_text: string | null;
  requester_id: string; plant: string; company_code: string; status: string; total_minor: number;
  budget_result: { outcome?: string; checks?: BudgetCheck[] } | null; policy_hints: string[] | null; approval_chain: string[] | null;
  rule_set_version: string | null; submitted_at: string | null; approved_at: string | null; created_at: string; lines?: PrLine[];
};

export const PURCHASE_TYPES = ['NON_STOCK', 'SERVICE', 'EXPENSE', 'ASSET'];
export const ACCOUNT_TYPES = ['COST_CENTER', 'WBS', 'ORDER', 'ASSET'];
/** Purchase types that need an account assignment before submission (P08). */
export const NEEDS_ACCOUNT = ['NON_STOCK', 'SERVICE', 'EXPENSE', 'ASSET'];

/** Problem box that also lists the individual policy violations the API returns. */
export function PolicyProblem({ error }: { error: ApiError | Error | null | undefined }) {
  if (!error) return null;
  const violations = (error as ApiError).problem?.violations;
  return (
    <div className="space-y-1">
      <ProblemBox error={error} />
      {Array.isArray(violations) && violations.length > 1 && (
        <ul className="list-disc pl-6 text-sm text-red-900">{violations.map((v) => <li key={String(v)}>{String(v)}</li>)}</ul>
      )}
    </div>
  );
}

/** Account assignment type + code; codes come from the cost objects in reference data. */
export function AccountAssignment({ type, code, onChange, costObjects, required }: {
  type: string; code: string; onChange: (type: string, code: string) => void; costObjects: Reference['costObjects']; required?: boolean;
}) {
  const matching = costObjects.filter((c) => c.type === type);
  return (
    <>
      <Field label={`Account assignment type${required ? ' *' : ''}`}>{(id) => (
        <Select id={id} value={type} onChange={(e) => onChange(e.target.value, '')}
          options={[{ value: '', label: '— none —' }, ...ACCOUNT_TYPES.map((t) => ({ value: t, label: label(t) }))]} />
      )}</Field>
      <Field label={`Account assignment code${required ? ' *' : ''}`} hint={type && !matching.length ? 'No master data for this type; enter the code' : undefined}>{(id) => (
        matching.length ? (
          <Select id={id} value={code} onChange={(e) => onChange(type, e.target.value)} disabled={!type}
            options={[{ value: '', label: 'Select…' }, ...matching.map((c) => ({ value: c.code, label: `${c.code} · ${c.name}` }))]} />
        ) : (
          <Input id={id} value={code} onChange={(e) => onChange(type, e.target.value)} disabled={!type} placeholder={type ? 'Code' : 'Choose a type first'} />
        )
      )}</Field>
    </>
  );
}

/** REQ-02 submit: policy check, budget check (soft stop needs a justification) and approval routing (DMN-01). */
export function SubmitPanel({ pr, onDone }: { pr: Pick<Requisition, 'number' | 'total_minor'>; onDone?: (result: Requisition) => void }) {
  const [justification, setJustification] = useState('');
  const [requestSourcing, setRequestSourcing] = useState(false);
  const submit = useCommand(() => api.post<Requisition>(`/requisitions/${pr.number}/submit`, {
    justification: justification.trim() || undefined, request_sourcing: requestSourcing,
  }), { success: (r) => `${r.number} submitted: ${label(r.status)}`, onSuccess: onDone });
  const code = submit.error?.problem?.code;
  const result = submit.data;

  if (result) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{result.number}</span><StatusChip status={result.status} />
        </div>
        <p className="mt-1">Approval route: {result.approval_chain?.length ? result.approval_chain.map(label).join(' → ') : 'none — auto-approved by policy (DMN-01)'}</p>
        <p>Budget: {label(result.budget_result?.outcome ?? '')}</p>
        {result.policy_hints?.length ? <p className="text-amber-800">Policy hints: {result.policy_hints.join('; ')}</p> : null}
        <Link href={`/pic/requisitions/${result.number}`} className="mt-2 inline-block font-medium text-[#1A56DB] hover:underline">Open {result.number} →</Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Submitting runs the policy checks (purpose code, account assignment, quote policy for free text), checks budget for {inr(pr.total_minor)} and
        routes the requisition for approval.
      </p>
      <Field label={`Budget justification${code === 'BUDGET_JUSTIFICATION_REQUIRED' ? ' *' : ' (optional)'}`}
        hint="Only needed when a cost object is over budget with a soft stop. Hard stops cannot be justified.">{(id) => (
        <Textarea id={id} value={justification} onChange={(e) => setJustification(e.target.value)}
          className={code === 'BUDGET_JUSTIFICATION_REQUIRED' ? 'border-amber-400' : ''} />
      )}</Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5" checked={requestSourcing} onChange={(e) => setRequestSourcing(e.target.checked)} />
        <span>Request a sourcing event instead of attaching three quotes (high-value free-text lines)</span>
      </label>
      <PolicyProblem error={submit.error} />
      <div className="flex justify-end">
        <Button variant="primary" busy={submit.isPending}
          disabled={code === 'BUDGET_JUSTIFICATION_REQUIRED' && !justification.trim()} onClick={() => submit.mutate()}>Submit for approval</Button>
      </div>
    </div>
  );
}
