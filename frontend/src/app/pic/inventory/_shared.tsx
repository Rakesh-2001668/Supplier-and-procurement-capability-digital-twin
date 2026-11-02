'use client';

import Link from 'next/link';
import { ReactNode, useEffect, useState } from 'react';
import { useToast } from '@/components/pic/toast';
import { Button, Dialog, Field, Input, Select, Textarea } from '@/components/pic/ui';
import { inr, label, qty as formatQty } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { today } from '../invoices/_components';
import { downloadFile } from '../purchase-orders/[ref]/_ops';

export { today };

// ---------------------------------------------------------------- API shapes (backend/app/pic/views.py, services/stock_reads.py)
export type UserRef = { id: string; name: string; email: string } | null;

export type StockRow = {
  id: string; material: string; description: string; uom: string; materialGroup: string | null; plant: string; storageLocation: string; stockType: string;
  batch: string; qty: string; expiry: string | null; daysToExpiry: number | null; unitPriceMinor: number | null; valueMinor: number | null;
  safetyStock: string; reorderPoint: string | null; belowSafety: boolean; daysOfCover: string | null; updatedAt: string;
};

export type Movement = {
  id: string; createdAt: string; material: string; description: string; uom: string; plant: string; storageLocation: string; stockType: string; batch: string;
  movementType: string; movementText: string; qty: string; valueMinor: number | null; valuedAtPosting: boolean; reasonCode: string | null; postingRef: string | null;
  reference: { type: string; ref: string; id: string; path: string | null }; actor: { id: string; name: string; email: string } | null;
};

type Rule<B> = { key: string; ref: string; body: B };
export type InventoryRules = {
  posting: Rule<{ autoPostBelowMinor: number; autoPostTypes: string[]; reasonRequiredFor: string[]; scrapReasons: Record<string, string>;
    blockReasons: Record<string, string>; crossPlantTransfer: boolean; maxLines: number; approvalBands: { upTo: number | null; chain: string[] }[] }>;
  count: Rule<{ qtyTolerancePct: string; valueToleranceMinor: number; recountDifferentCounter: boolean; maxLines: number }>;
  reservation: Rule<{ blockWhenUnavailable: boolean; graceDays: number; requireCostObject: boolean; purposes: string[]; maxOpenDays: number }>;
  alerts: Rule<{ qualityHoldDays: number; blockedDays: number; expiryWarnDays: number }>;
  enums: { postingTypes: string[]; postingStatuses: string[]; countStatuses: string[]; reservationStatuses: string[]; stockTypes: string[]; alertTypes: string[];
    movementTypes: Record<string, string> };
  me: { canPost: boolean; canCount: boolean; canApprove: boolean; plants: string[] | string | null };
};

type Reference = {
  plants: { code: string; name: string }[];
  costObjects: { type: string; code: string; name: string }[];
  materials: { number: string; description: string; uom: string }[];
};

// ---------------------------------------------------------------- data hooks
export const useRules = () => useApi<InventoryRules>('/inventory/rules');
export const useReference = () => useApi<Reference>('/reference');

/** The plants the user may use in forms: the reference plants, narrowed to the user's own plants when the profile lists them. */
export function usePlants() {
  const reference = useReference();
  const rules = useRules();
  const allowed = rules.data?.me.plants;
  const plants = (reference.data?.plants ?? []).filter((p) => !Array.isArray(allowed) || allowed.includes('*') || allowed.includes(p.code));
  return { plants, loading: reference.isLoading || rules.isLoading };
}

/** Storage locations seen in the stock of a plant (there is no master-data list endpoint for them). */
export function useSlocs(plant: string) {
  const stock = useApi<{ items: StockRow[] }>(plant ? `/stock?plant=${encodeURIComponent(plant)}&limit=200` : null);
  return [...new Set((stock.data?.items ?? []).map((s) => s.storageLocation))].sort();
}

export function useDebounced<T>(value: T, ms = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

// ---------------------------------------------------------------- small helpers
export type QueryValue = string | number | boolean | null | undefined;

export function qs(params: Record<string, QueryValue>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue;
    query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}

const encode = encodeURIComponent;
export const materialHref = (material: string) => `/pic/inventory/${encode(material)}`;
export const postingHref = (number: string) => `/pic/inventory/postings/${encode(number)}`;
export const countHref = (number: string) => `/pic/inventory/counts/${encode(number)}`;
export const reservationHref = (number: string) => `/pic/inventory/reservations/${encode(number)}`;

/** Where a ledger reference (the document that caused a movement) is shown; null when it has no screen of its own. */
export function referenceHref(type: string, ref: string): string | null {
  switch (type) {
    case 'GOODS_RECEIPT': return `/pic/receiving/${encode(ref)}`;
    case 'STOCK_POSTING': return postingHref(ref);
    case 'PHYSICAL_INVENTORY': return countHref(ref);
    case 'STOCK_RESERVATION': return reservationHref(ref);
    case 'PURCHASE_ORDER': return `/pic/purchase-orders/${encode(ref)}`;
    default: return null;
  }
}

export const REFERENCE_TYPES = ['GOODS_RECEIPT', 'INSPECTION_LOT', 'RETURN_DELIVERY', 'STOCK_POSTING', 'PHYSICAL_INVENTORY', 'STOCK_RESERVATION', 'PURCHASE_ORDER'];

export function RefLink({ type, docRef }: { type: string; docRef: string }) {
  const href = referenceHref(type, docRef);
  return (
    <span className="whitespace-nowrap">
      <span className="text-xs text-slate-500">{label(type)} </span>
      {href ? <Link href={href} prefetch={false} className="font-medium text-[#1A56DB] hover:underline">{docRef}</Link> : <span className="font-medium">{docRef}</span>}
    </span>
  );
}

export function MaterialLink({ material, description }: { material: string; description?: string }) {
  return (
    <div className="min-w-0">
      <Link href={materialHref(material)} prefetch={false} className="font-medium text-[#1A56DB] hover:underline">{material}</Link>
      {description && <p className="max-w-[16rem] truncate text-xs text-slate-500" title={description}>{description}</p>}
    </div>
  );
}

/** Quantity with an explicit sign (the ledger shows + and - so direction never relies on colour). */
export function signedQty(value: string | number | null | undefined, uom?: string): string {
  if (value === null || value === undefined || value === '') return '–';
  const n = Number(value);
  return `${n > 0 ? '+' : ''}${formatQty(n)}${uom ? ` ${uom}` : ''}`;
}

export function signedInr(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '–';
  return `${minor > 0 ? '+' : ''}${inr(minor)}`;
}

type Tone = 'good' | 'warn' | 'bad' | 'info' | 'muted';
const TONES: Record<Tone, string> = {
  good: 'bg-emerald-50 text-emerald-800 ring-emerald-200', warn: 'bg-amber-50 text-amber-800 ring-amber-200', bad: 'bg-red-50 text-red-800 ring-red-200',
  info: 'bg-blue-50 text-blue-800 ring-blue-200', muted: 'bg-slate-100 text-slate-700 ring-slate-200',
};

/** Text label with a tone: the words carry the meaning, the colour only supports them. */
export function Flag({ tone = 'info', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${TONES[tone]}`}>{children}</span>;
}

export function SeverityChip({ severity }: { severity: string }) {
  const tone: Tone = severity === 'CRITICAL' ? 'bad' : severity === 'HIGH' ? 'warn' : severity === 'MEDIUM' ? 'info' : 'muted';
  return <Flag tone={tone}>{severity === 'CRITICAL' ? '!! ' : severity === 'HIGH' ? '! ' : ''}{label(severity)}</Flag>;
}

export function ExpiryCell({ expiry, days }: { expiry: string | null; days: number | null }) {
  if (!expiry) return <span className="text-slate-500">–</span>;
  const tone: Tone | null = days === null ? null : days < 0 ? 'bad' : days <= 30 ? 'warn' : null;
  return (
    <div className="text-xs">
      <p>{expiry}</p>
      {tone && days !== null && <Flag tone={tone}>{days < 0 ? `Expired ${-days} d ago` : `${days} d left`}</Flag>}
    </div>
  );
}

// ---------------------------------------------------------------- form pieces
export function TextFilter({ label: name, value, onChange, placeholder, type = 'text', hint }: {
  label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string; hint?: string;
}) {
  return <Field label={name} hint={hint}>{(id, describedBy) => <Input id={id} aria-describedby={describedBy} type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />}</Field>;
}

export function SelectFilter({ label: name, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) {
  return <Field label={name}>{(id) => <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} options={options} />}</Field>;
}

export function CheckFilter({ label: name, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 self-end rounded-lg border border-slate-200 px-3 py-2 text-sm">
      <input type="checkbox" className="h-4 w-4 accent-[#1A56DB]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {name}
    </label>
  );
}

export function FilterBar({ name, children }: { name: string; children: ReactNode }) {
  return <div role="search" aria-label={name} className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}

export function PlantSelect({ value, onChange, all = true, name = 'Plant', required }: { value: string; onChange: (value: string) => void; all?: boolean; name?: string; required?: boolean }) {
  const { plants } = usePlants();
  const options = [...(all ? [{ value: '', label: 'All plants' }] : [{ value: '', label: 'Choose a plant' }]), ...plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))];
  return <Field label={name} required={required}>{(id) => <Select id={id} value={value} onChange={(e) => onChange(e.target.value)} options={options} />}</Field>;
}

/** Material number input with the master list as suggestions; shows the description once the number is known. */
export function MaterialInput({ value, onChange, name = 'Material', required }: { value: string; onChange: (value: string) => void; name?: string; required?: boolean }) {
  const reference = useReference();
  const known = reference.data?.materials.find((m) => m.number === value.trim());
  return (
    <Field label={name} required={required} hint={known ? `${known.description} · ${known.uom}` : undefined}>
      {(id, describedBy) => <>
        <Input id={id} aria-describedby={describedBy} list={`${id}-materials`} value={value} placeholder="Material number" autoComplete="off" onChange={(e) => onChange(e.target.value)} />
        <datalist id={`${id}-materials`}>{(reference.data?.materials ?? []).map((m) => <option key={m.number} value={m.number}>{m.description}</option>)}</datalist>
      </>}
    </Field>
  );
}

/** Storage location input with the locations that hold stock in the plant as suggestions. */
export function SlocInput({ plant, value, onChange, name = 'Storage location', required, hint }: { plant: string; value: string; onChange: (value: string) => void; name?: string; required?: boolean; hint?: string }) {
  const slocs = useSlocs(plant);
  return (
    <Field label={name} required={required} hint={hint}>
      {(id, describedBy) => <>
        <Input id={id} aria-describedby={describedBy} list={`${id}-slocs`} maxLength={10} value={value} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
        <datalist id={`${id}-slocs`}>{slocs.map((s) => <option key={s} value={s} />)}</datalist>
      </>}
    </Field>
  );
}

/** Download an API file through the same-origin proxy; a problem+json answer is shown as a toast. */
export function ExportButton({ path, fileName, children }: { path: string; fileName: string; children: ReactNode }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button busy={busy} onClick={async () => {
      setBusy(true);
      try {
        await downloadFile(path, fileName);
      } catch (error) {
        toast.problem(error as Error);
      } finally {
        setBusy(false);
      }
    }}>{children}</Button>
  );
}

export const isQty = (value: string) => value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) > 0;

/** A confirm dialog that asks for a reason or comment (reject, cancel and approve all keep theirs in the audit trail). */
export function ReasonDialog({ title, intro, fieldLabel, required, confirm, variant = 'primary', busy, onConfirm, onClose }: {
  title: string; intro?: ReactNode; fieldLabel: string; required: boolean; confirm: string; variant?: 'primary' | 'danger'; busy?: boolean;
  onConfirm: (text: string) => void; onClose: () => void;
}) {
  const [text, setText] = useState('');
  const missing = required && text.trim().length < 3;
  return (
    <Dialog open title={title} onClose={onClose}>
      {intro && <div className="mb-3 text-sm text-slate-700">{intro}</div>}
      <Field label={fieldLabel} required={required} hint={required ? 'At least 3 characters; kept in the audit trail' : 'Optional; kept in the audit trail'}>
        {(id, describedBy) => <Textarea id={id} aria-describedby={describedBy} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />}
      </Field>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Back</Button>
        <Button variant={variant} disabled={missing} busy={busy} onClick={() => onConfirm(text.trim())}>{confirm}</Button>
      </div>
    </Dialog>
  );
}
