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
/** §24.1 / M01 category-plan budget check at submit (rule CATEGORY-BUDGET). */
export type CategoryBudgetCheck = {
  category: string; plan: string; budgetMinor: number; committedMinor: number; requisitionMinor: number; projectedMinor: number;
  availableMinor: number; usedPct: string; warnAtPct: string; mode: 'SOFT' | 'HARD'; result: string; ruleSetVersion: string; justification?: string;
};
export type CategoryBudget = { outcome: string; fiscalYear: string; measure: string; checks: CategoryBudgetCheck[]; warnings: string[] };

function CategoryBudgetLine({ check }: { check: CategoryBudgetCheck }) {
  return (
    <li>
      <span className="font-mono text-xs">{check.category}</span> · plan {check.plan}: {check.usedPct}% of {inr(check.budgetMinor)}
      {' '}(committed {inr(check.committedMinor)} + this requisition {inr(check.requisitionMinor)}) · {check.mode === 'HARD' ? 'hard stop' : 'soft stop'} above 100%,
      warning from {check.warnAtPct}%
    </li>
  );
}
export type Allocation = { qty: string; share: string | number | null; supplier: string; contractId: string | null; priceSource: string; unitPriceMinor: number | null };

export type PrLine = {
  id: string; line_no: number; item_type: string; purchase_type: string; material_id: string | null; catalogue_item_id: string | null;
  contract_line_id: string | null; description: string; material_group: string | null; category: string | null; qty: string; uom: string; price_est_minor: number;
  account_assignment_type: string | null; account_assignment_code: string | null; need_date: string; plant: string;
  quotes_attached: number; reusable: boolean; mdm_request_id: string | null; ordered_qty: string; sourcing_status: string | null;
  source_determination: { method?: string; allocations?: Allocation[]; quotes?: { supplier: string; reference: string; date: string }[] } | null;
  planned_order_id: string | null;
};

/** Free-text and free-service lines (no material, catalogue item or contract line): the quote policy applies. */
export const isUnstructured = (l: Pick<PrLine, 'material_id' | 'catalogue_item_id' | 'contract_line_id'>) =>
  !l.material_id && !l.catalogue_item_id && !l.contract_line_id;

export type Requisition = {
  id: string; number: string; origin: string; origin_ref: string | null; purpose_code: string | null; purpose_text: string | null;
  requester_id: string; plant: string; company_code: string; status: string; total_minor: number;
  budget_result: { outcome?: string; checks?: BudgetCheck[]; categoryBudget?: CategoryBudget } | null; policy_hints: string[] | null; approval_chain: string[] | null;
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
  const needsJustification = code === 'BUDGET_JUSTIFICATION_REQUIRED' || code === 'CATEGORY_BUDGET_JUSTIFICATION_REQUIRED';
  const refusedCategory = submit.error?.problem?.categoryBudget as CategoryBudgetCheck | undefined;
  const categoryResult = result?.budget_result?.categoryBudget;

  if (result) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{result.number}</span><StatusChip status={result.status} />
        </div>
        <p className="mt-1">Approval route: {result.approval_chain?.length ? result.approval_chain.map(label).join(' → ') : 'none — auto-approved by policy (DMN-01)'}</p>
        <p>Budget: {label(result.budget_result?.outcome ?? '')}</p>
        {categoryResult && categoryResult.checks.length > 0 && (
          <div className={categoryResult.outcome === 'OK' ? '' : 'text-amber-800'}>
            <p>Category budget {categoryResult.fiscalYear}: {label(categoryResult.outcome)}</p>
            <ul className="list-disc pl-5 text-xs">{categoryResult.checks.map((c) => <CategoryBudgetLine key={c.category} check={c} />)}</ul>
          </div>
        )}
        {result.policy_hints?.length ? <p className="text-amber-800">Policy hints: {result.policy_hints.join('; ')}</p> : null}
        <Link href={`/pic/requisitions/${result.number}`} className="mt-2 inline-block font-medium text-[#1A56DB] hover:underline">Open {result.number} →</Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Submitting runs the policy checks (purpose code, account assignment, stock needs a material, quote policy for free-text and service lines
        without a material, catalogue item or contract), checks budget for {inr(pr.total_minor)} and
        routes the requisition for approval.
      </p>
      <Field label={`Budget justification${needsJustification ? ' *' : ' (optional)'}`}
        hint="Only needed when a cost object or the category plan is over budget with a soft stop. Hard stops cannot be justified.">{(id) => (
        <Textarea id={id} value={justification} onChange={(e) => setJustification(e.target.value)}
          className={needsJustification ? 'border-amber-400' : ''} />
      )}</Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5" checked={requestSourcing} onChange={(e) => setRequestSourcing(e.target.checked)} />
        <span>Request a sourcing event instead of attaching three quotes (high-value free-text lines)</span>
      </label>
      <PolicyProblem error={submit.error} />
      {refusedCategory && (
        <div className={`rounded-lg border px-3 py-2 text-sm ${code === 'CATEGORY_BUDGET_EXCEEDED' ? 'border-red-200 bg-red-50 text-red-900' : 'border-amber-300 bg-amber-50 text-amber-900'}`}>
          <p className="font-semibold">{code === 'CATEGORY_BUDGET_EXCEEDED' ? 'Category budget exhausted (hard stop)' : 'Category budget exceeded – justification required'}</p>
          <ul className="list-disc pl-5 text-xs"><CategoryBudgetLine check={refusedCategory} /></ul>
          {code === 'CATEGORY_BUDGET_EXCEEDED' && <p className="mt-1 text-xs">Reduce the value or ask the category owner to raise the approved plan budget.</p>}
        </div>
      )}
      <div className="flex justify-end">
        <Button type="button" variant="primary" busy={submit.isPending}
          disabled={needsJustification && !justification.trim()} onClick={() => submit.mutate()}>Submit for approval</Button>
      </div>
    </div>
  );
}
