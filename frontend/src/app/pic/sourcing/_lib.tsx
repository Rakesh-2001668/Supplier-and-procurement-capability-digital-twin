'use client';

// Shared pieces of the M05 sourcing screens: the event document with its ETag (If-Match on the commands), role checks, CSV download.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useSyncExternalStore } from 'react';
import { useToast } from '@/components/pic/toast';
import { api, ApiError, readSessionUser } from '@/lib/pic/api';

// ---------------------------------------------------------------- ETag of the event document (API-3)
// lib/pic/api.ts remembers the ETag of two-segment document URLs only; the event lives at /sourcing/events/{ref}, so it is kept here.
const etags = new Map<string, string>();

export function etagOf(path: string): string | undefined {
  return etags.get(path);
}

/** GET the event with its ETag. Same query key as useApi(path), so every invalidation refreshes it. */
export function useEventDoc<T>(path: string) {
  return useQuery<T, ApiError>({
    queryKey: [path],
    queryFn: async () => {
      const response = await fetch(`/api/pic/v1${path}`, { headers: { accept: 'application/json' }, cache: 'no-store' });
      if (response.status === 401 && typeof window !== 'undefined' && !window.location.pathname.startsWith('/pic/login')) {
        window.location.href = `/pic/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      }
      const tag = response.headers.get('etag');
      if (tag) etags.set(path, tag);
      const text = await response.text();
      const data = text ? JSON.parse(text) : null;
      if (!response.ok) throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...(data ?? {}) });
      return data as T;
    },
    retry: (count, error) => count < 2 && (error as ApiError).status >= 500,
  });
}

/**
 * A command on the event. It sends the ETag the screen last read as If-Match; when somebody else changed the event meanwhile the API answers 412
 * and the screen reloads the event so the user sees what changed before trying again.
 */
export function useEventCommand<TArgs = void, TResult = unknown>(
  path: string,
  run: (args: TArgs, ifMatch: string | undefined) => Promise<TResult>,
  options: { success?: string | ((result: TResult) => string); onSuccess?: (result: TResult) => void; onError?: (error: ApiError) => void; quiet?: boolean } = {},
) {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation<TResult, ApiError, TArgs>({
    mutationFn: (args) => run(args, etags.get(path)),
    onSuccess: async (result) => {
      await client.invalidateQueries();
      if (options.success) toast.success(typeof options.success === 'function' ? options.success(result) : options.success);
      options.onSuccess?.(result);
    },
    onError: async (error) => {
      if (error.status === 412) {
        await client.invalidateQueries();
        toast.problem(new ApiError({ ...error.problem, detail: `${error.problem.detail ?? 'The event changed.'} The screen has reloaded the latest version: check it and repeat the action.` }));
      } else if (!options.quiet) {
        toast.problem(error);
        await client.invalidateQueries();
      }
      options.onError?.(error);
    },
  });
}

export function ifMatchOptions(ifMatch: string | undefined) {
  return ifMatch ? { ifMatch } : undefined;
}

// ---------------------------------------------------------------- roles
const noSubscribe = () => () => {};

/** Roles from the session cookie; null while rendering on the server. */
export function useRoles(): string[] | null {
  const cookie = useSyncExternalStore(noSubscribe, () => document.cookie, () => null);
  return useMemo(() => (cookie === null ? null : readSessionUser()?.roles ?? []), [cookie]);
}

export const MANAGE_ROLES = ['BUYER', 'CATEGORY_MANAGER', 'TENANT_ADMIN'];
export const EVALUATE_ROLES = ['CATEGORY_MANAGER', 'QUALITY_INSPECTOR'];

export function useCan() {
  const roles = useRoles();
  return (allowed: string[]) => !!roles && (roles.length === 0 || roles.some((r) => allowed.includes(r)));
}

// ---------------------------------------------------------------- CSV with its hash
export type CsvDownload = { filename: string; sha256: string | null; rows: string | null; text: string; bytes: number };

/** Fetch a CSV through the same-origin proxy; the SHA-256 the server computed travels in X-Content-SHA256. */
export async function fetchCsv(path: string): Promise<CsvDownload> {
  const response = await fetch(`/api/pic/v1${path}`, { cache: 'no-store' });
  const text = await response.text();
  if (!response.ok) {
    let data: Record<string, unknown> = {};
    try { data = JSON.parse(text); } catch { /* not JSON */ }
    throw new ApiError({ status: response.status, code: String(data.code ?? 'ERROR'), ...data });
  }
  const disposition = response.headers.get('content-disposition') ?? '';
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? 'export.csv';
  return { filename: name, sha256: response.headers.get('x-content-sha256'), rows: response.headers.get('x-rows'), text, bytes: new TextEncoder().encode(text).length };
}

export function saveFile(download: CsvDownload) {
  const url = URL.createObjectURL(new Blob([download.text], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = download.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- shapes of the second-pass views
export type TcoParts = Record<string, number>;
export type TcoLine = {
  line: number; eventLineId: string; lot: string | null; priceMinor: number; tcoMinor: number; tco: TcoParts | null; leadTimeDays: number; paymentTermsDays: number;
  verifiedCapacityPerMonth: string | null; capacityVerified: boolean; moq: string | null; twinCapacityPerMonth: string | null; currency: string;
  quotedPriceMinor: number | null; fxRate: string | null; incoterm: string | null; origin: string | null; tcoIncomplete: boolean; tcoMissing: string[];
  weightedScore?: string; tcoTrace?: TraceItem[]; trace?: TraceItem[];
};
export type TraceItem = { component: string; valueMinor?: string; status?: string; formula?: string; inputs?: Record<string, unknown>; steps?: unknown };
export type TechnicalGate = { passed: boolean; failed: string[]; pending: string[]; thresholds: Record<string, string> };
export type CompareRow = {
  supplier: string; supplierId: string; round: number; bidId: string; submittedAt: string; validUntil: string | null; lateDeliveryProb: string | null;
  lines: TcoLine[]; lots: { lot: string; discountPct: string; allOrNothing: boolean }[]; autoScores: Record<string, { score: string; source: string; noData: boolean }>;
  basis: 'UNIT' | 'ANNUAL_VALUE'; coverage: { bid: number; of: number }; complete: boolean; tcoIncomplete: boolean; tcoMissing: string[];
  priceMinor: number; tcoMinor: number; tco?: TcoParts; leadTimeDays: number; paymentTermsDays: number; verifiedCapacityPerMonth: string | null;
  capacityVerified: boolean; moq?: string | null; shouldCostDeltaMinor: number | null; scores?: Record<string, string>; weightedScore?: string; priceScore?: string;
  evaluators?: number; unscored?: string[]; technicalGate?: TechnicalGate; rank: number; tiedWithPrevious: boolean; flags: string[];
};
export type Screens = {
  outliers: { supplier: string; flag: string; detail: string; pct?: string; z?: number }[];
  collusion: { hint: string; suppliers: string[]; detail: string }[]; notChecked: string[];
};
export type Comparison = {
  event: string; status: string; round: number; scoringMethod: string; currency: string; referenceDate: string | null; competitive: boolean | null;
  minBidders: number | null; validBidders: number; baselineMinor: number | null; baselineMethod: string | null;
  shouldCost: { unitCost: string; unitCostMinor: number; model: string } | null;
  benchmark: { points: Record<string, { priceMinor: number; source: string; asOf?: string }>; lowMinor: number | null; highMinor: number | null; medianMinor: number | null } | null;
  bids: CompareRow[]; excludedBids: { supplier: string; status: string; round: number; reason: string | null }[]; screens: Screens;
};

export const TCO_LABELS: [string, string][] = [
  ['price', 'Price (normalised to INR per base unit)'], ['freight', 'Freight'], ['duty', 'Customs duty'], ['packaging', 'Packaging'],
  ['carrying', 'Carrying cost (lead time and safety stock)'], ['quality', 'Quality cost (PPM x cost of poor quality)'], ['paymentTermValue', 'Payment-term value'],
];

export const SCORING_METHODS = [
  { value: 'LOWEST_RATIO', label: 'Lowest ratio (lowest cost / this cost x 100)' },
  { value: 'MIN_MAX', label: 'Min-max (spread between lowest and highest)' },
  { value: 'RANK', label: 'Rank (100 x (n - rank + 1) / n)' },
];

export const BASELINE_METHODS = [
  { value: 'LAST_PRICE', label: 'Last price paid (info record)' },
  { value: 'WEIGHTED_AVG', label: 'Weighted average of the last 12 months of orders' },
  { value: 'SHOULD_COST', label: 'Should-cost model' },
  { value: 'MARKET_INDEX', label: 'Market benchmark (latest market price)' },
  { value: 'BUDGET', label: 'Budget price (given)' },
  { value: 'MANUAL', label: 'Manual (given)' },
];

export const FLAG_TEXT: Record<string, string> = {
  LOW_VS_MEDIAN: 'abnormally low', HIGH_VS_MEDIAN: 'abnormally high', Z_SCORE: 'statistical outlier', LOW_VS_SHOULD_COST: 'far below should-cost',
};

/** The api helper's post with the event's own If-Match. */
export function postEvent<T>(path: string, body: unknown, ifMatch: string | undefined) {
  return api.post<T>(path, body, ifMatchOptions(ifMatch));
}

// ---------------------------------------------------------------- SOURCING-POLICY in force (read-only: GET /v1/admin/rules)
export type SourcingPolicy = {
  maxExtensions?: number; priceBand?: { minVsBaseline: string; maxVsBaseline: string }; minRationaleChars?: number; twoPersonOpening?: boolean;
  minBidders?: number; budgetCheck?: string; minOpenHours?: Record<string, number>; requireAllCriteriaScored?: boolean; clarificationCloseHours?: number;
};
type RuleRow = { key: string; version?: string; effective_from?: string; effective_to?: string | null; body: SourcingPolicy };

export function useSourcingPolicy(): SourcingPolicy | undefined {
  const { data } = useQuery<RuleRow[], ApiError>({
    queryKey: ['/admin/rules'],
    queryFn: () => api.get<RuleRow[]>('/admin/rules'),
    staleTime: 300000,
  });
  return useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    const rows = (data ?? []).filter((r) => r.key === 'SOURCING-POLICY' && (!r.effective_from || r.effective_from.slice(0, 10) <= today) && (!r.effective_to || r.effective_to.slice(0, 10) >= today));
    return rows.sort((a, b) => String(b.effective_from).localeCompare(String(a.effective_from)))[0]?.body;
  }, [data]);
}
