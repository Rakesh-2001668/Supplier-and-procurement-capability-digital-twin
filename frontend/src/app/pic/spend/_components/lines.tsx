'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Button, Card, DataTable, Dialog, Empty, Facts, Field, Input, Kpi, Loading, ProblemBox, Select, StatusChip } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { crore, date, inr, label } from '@/lib/pic/format';
import { useToast } from '@/components/pic/toast';
import { useApi } from '@/lib/pic/hooks';
import { SpendProblem } from './shared';

export type SpendLineRow = {
  lineId: string; period: string; documentType: 'INVOICE' | 'CREDIT_NOTE' | 'DEBIT_NOTE'; documentRef: string | null; documentDate: string | null; invoice: string | null; po: string | null;
  supplier: string; supplierName: string; category: string; plant: string | null; companyCode: string | null; costObject: string | null; currency: string; amountMinor: number;
  amountGroupMinor: number | null; fxRate: string | null; contracted: boolean; addressable: boolean; maverickFlags: string[]; priceVarianceMinor: number; description: string | null;
  source: string; sourceSystem: string | null; lineage: { invoice: string | null; purchaseOrder: string | null; note: string | null };
};
type LinesPage = { lines: SpendLineRow[]; nextCursor: string | null; matching: number; matchingGroupMinor: number; currency: string };

type Filters = {
  periodFrom: string; periodTo: string; category: string; supplier: string; parent: string; plant: string; companyCode: string; documentType: string;
  buyer: string; contracted: string; maverick: string; currency: string;
};
const KEYS: [keyof Filters, string][] = [['periodFrom', 'period_from'], ['periodTo', 'period_to'], ['category', 'category'], ['supplier', 'supplier'], ['parent', 'parent'], ['plant', 'plant'],
  ['companyCode', 'company_code'], ['documentType', 'document_type'], ['buyer', 'buyer'], ['contracted', 'contracted'], ['maverick', 'maverick'], ['currency', 'currency']];

function toQuery(f: Filters, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams(extra);
  for (const [k, name] of KEYS) if (f[k]) q.set(name, f[k]);
  return q.toString();
}

const DOC_TYPES = [{ value: '', label: 'All documents' }, { value: 'INVOICE', label: 'Invoices' }, { value: 'CREDIT_NOTE', label: 'Credit notes' }, { value: 'DEBIT_NOTE', label: 'Debit notes' }];
const TRI = [{ value: '', label: 'Both' }, { value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }];

type ExportResult = { fileName: string; rows: number; truncated: boolean; sha256: string; verified: boolean | null; bytes: number; kind: string };

async function sha256Hex(buffer: ArrayBuffer): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
  } catch {
    return null;
  }
}

/** Drill from a cube slice to its spend lines (keyset cursor) with the document lineage, and export the slice as CSV with its SHA-256. */
export function LinesTab() {
  const params = useSearchParams();
  const initial: Filters = {
    periodFrom: params.get('period_from') ?? '', periodTo: params.get('period_to') ?? '', category: params.get('category') ?? '', supplier: params.get('supplier') ?? '',
    parent: params.get('parent') ?? '', plant: params.get('plant') ?? '', companyCode: params.get('company_code') ?? '', documentType: params.get('document_type') ?? '',
    buyer: params.get('buyer') ?? '', contracted: params.get('contracted') ?? '', maverick: params.get('maverick') ?? '', currency: params.get('currency') ?? '',
  };
  const [draft, setDraft] = useState<Filters>(initial);
  const [applied, setApplied] = useState<Filters>(initial);
  const [lineage, setLineage] = useState<SpendLineRow | null>(null);
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setDraft((cur) => ({ ...cur, [key]: value }));
  const plants = useApi<{ plants: { code: string; name: string }[] }>('/reference').data?.plants ?? [];
  const base = `/spend/lines?${toQuery(applied, { limit: '100' })}`;
  const query = useInfiniteQuery<LinesPage, ApiError>({
    queryKey: [base, 'lines'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api.get<LinesPage>(pageParam ? `${base}&cursor=${encodeURIComponent(String(pageParam))}` : base),
    getNextPageParam: (last) => last.nextCursor,
  });
  const lines = query.data?.pages.flatMap((p) => p.lines) ?? [];
  const first = query.data?.pages[0];

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        The posted lines behind a cube figure, newest period first, with the document each one came from: invoice, purchase order and, for a credit or debit note, the note.
        Pages are read with a cursor, so the list stays stable while new documents are posted.
      </p>
      <Card title="Filters">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); setApplied(draft); }}>
          <div className="grid gap-3 md:grid-cols-4">
            <Field label="From month">{(id) => <Input id={id} type="month" value={draft.periodFrom} onChange={(e) => set('periodFrom', e.target.value)} />}</Field>
            <Field label="To month">{(id) => <Input id={id} type="month" value={draft.periodTo} onChange={(e) => set('periodTo', e.target.value)} />}</Field>
            <Field label="Category (any level)">{(id) => <Input id={id} value={draft.category} onChange={(e) => set('category', e.target.value.toUpperCase())} />}</Field>
            <Field label="Document">{(id) => <Select id={id} value={draft.documentType} onChange={(e) => set('documentType', e.target.value)} options={DOC_TYPES} />}</Field>
            <Field label="Supplier code">{(id) => <Input id={id} value={draft.supplier} onChange={(e) => set('supplier', e.target.value)} />}</Field>
            <Field label="Parent supplier code">{(id) => <Input id={id} value={draft.parent} onChange={(e) => set('parent', e.target.value)} />}</Field>
            <Field label="Plant">{(id) => (
              <Select id={id} value={draft.plant} onChange={(e) => set('plant', e.target.value)}
                options={[{ value: '', label: 'All plants' }, ...plants.map((p) => ({ value: p.code, label: `${p.code} · ${p.name}` }))]} />
            )}</Field>
            <Field label="Buyer (e-mail)">{(id) => <Input id={id} value={draft.buyer} onChange={(e) => set('buyer', e.target.value)} />}</Field>
            <Field label="Company code">{(id) => <Input id={id} value={draft.companyCode} onChange={(e) => set('companyCode', e.target.value)} />}</Field>
            <Field label="Contracted">{(id) => <Select id={id} value={draft.contracted} onChange={(e) => set('contracted', e.target.value)} options={TRI} />}</Field>
            <Field label="Maverick flag">{(id) => <Select id={id} value={draft.maverick} onChange={(e) => set('maverick', e.target.value)} options={TRI} />}</Field>
            <Field label="Currency">{(id) => <Input id={id} value={draft.currency} maxLength={3} onChange={(e) => set('currency', e.target.value.toUpperCase())} />}</Field>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary">Show lines</Button>
            <Button type="button" variant="ghost" onClick={() => { const empty = Object.fromEntries(KEYS.map(([k]) => [k, ''])) as Filters; setDraft(empty); setApplied(empty); }}>Clear filters</Button>
          </div>
        </form>
      </Card>

      {query.isLoading ? <Loading /> : query.error ? <SpendProblem error={query.error} /> : !first || !lines.length ? (
        <Empty title="No lines for these filters" hint="Widen the period or clear a filter." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Matching lines" value={first.matching.toLocaleString('en-IN')} hint={`${lines.length} loaded`} />
            <Kpi label="Net value" value={crore(first.matchingGroupMinor)} hint={`${inr(first.matchingGroupMinor)} · ${first.currency}`} />
          </div>
          <Card title="Spend lines">
            <DataTable<SpendLineRow & { id: string }> caption="Spend lines with document lineage" rows={lines.map((l) => ({ ...l, id: l.lineId }))}
              hasMore={!!query.hasNextPage} loadingMore={query.isFetchingNextPage} onLoadMore={() => query.fetchNextPage()} columns={[
                { key: 'period', header: 'Period', render: (l) => <span className="font-mono text-xs">{l.period}</span> },
                { key: 'documentType', header: 'Document', render: (l) => (
                  <span><StatusChip status={l.documentType === 'INVOICE' ? 'POSTED' : l.documentType === 'CREDIT_NOTE' ? 'CREDITED' : 'ACCRUED'} />
                    <span className="mt-0.5 block font-mono text-xs">{l.documentRef ?? l.invoice ?? '–'}</span></span>
                ) },
                { key: 'supplier', header: 'Supplier', render: (l) => <span><Link href={`/pic/suppliers/${encodeURIComponent(l.supplier)}`} className="font-mono text-xs font-medium text-[#1A56DB] hover:underline">{l.supplier}</Link><span className="block text-xs text-slate-500">{l.supplierName}</span></span> },
                { key: 'category', header: 'Category', render: (l) => <span className="font-mono text-xs">{l.category}</span> },
                { key: 'plant', header: 'Plant', render: (l) => l.plant ?? '–' },
                { key: 'description', header: 'Description', className: 'min-w-[200px]', render: (l) => <span className="text-slate-700">{l.description ?? '–'}</span> },
                { key: 'amountMinor', header: 'Amount', align: 'right', render: (l) => (
                  <span>{inr(l.amountGroupMinor ?? l.amountMinor)}{l.currency !== first.currency && <span className="block text-xs text-slate-500">{l.currency} {(l.amountMinor / 100).toLocaleString('en-IN')}{l.fxRate ? ` @ ${l.fxRate}` : ''}</span>}</span>
                ) },
                { key: 'flags', header: 'Flags', render: (l) => (
                  <span className="flex flex-wrap gap-1 text-[11px]">
                    <span className={`rounded px-1.5 py-0.5 ring-1 ring-inset ${l.contracted ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-slate-50 text-slate-600 ring-slate-200'}`}>{l.contracted ? 'contracted' : 'off contract'}</span>
                    {l.maverickFlags.map((f) => <span key={f} className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800 ring-1 ring-inset ring-amber-200">{label(f)}</span>)}
                  </span>
                ) },
                { key: 'lineage', header: '', render: (l) => <Button onClick={() => setLineage(l)} aria-label={`Show lineage of ${l.documentRef ?? l.invoice ?? l.lineId}`}>Lineage</Button> },
              ]} />
          </Card>
        </>
      )}

      <ExportCard filters={applied} />
      {lineage && <LineageDialog line={lineage} groupCurrency={first?.currency ?? 'INR'} onClose={() => setLineage(null)} />}
    </div>
  );
}

function LineageDialog({ line, groupCurrency, onClose }: { line: SpendLineRow; groupCurrency: string; onClose: () => void }) {
  const steps = [
    { name: 'Purchase order', ref: line.lineage.purchaseOrder, href: line.lineage.purchaseOrder ? `/pic/purchase-orders/${encodeURIComponent(line.lineage.purchaseOrder)}` : null, hint: 'Commitment; never counted as spend' },
    { name: 'Supplier invoice', ref: line.lineage.invoice, href: null, hint: 'Posted invoice line, net of tax' },
    { name: label(line.documentType), ref: line.lineage.note, href: null, hint: line.documentType === 'INVOICE' ? 'This line is the invoice itself' : 'Correction that nets against the invoice line' },
  ];
  return (
    <Dialog open title={`Document lineage – ${line.documentRef ?? line.invoice ?? 'line'}`} onClose={onClose}>
      <ol className="mb-4 space-y-2" aria-label="Document chain">
        {steps.map((s, i) => (
          <li key={s.name} className="flex items-start gap-3 rounded-lg border border-slate-200 px-3 py-2">
            <span className="mt-0.5 font-mono text-xs text-slate-500">{i + 1}</span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-900">{s.name}</p>
              <p className="text-sm">{s.ref ? (s.href ? <Link href={s.href} className="font-mono text-[#1A56DB] hover:underline">{s.ref}</Link> : <span className="font-mono">{s.ref}</span>) : <span className="text-slate-500">none (non-PO spend or no note)</span>}</p>
              <p className="text-xs text-slate-500">{s.hint}</p>
            </div>
          </li>
        ))}
      </ol>
      <Facts items={[
        ['Period', line.period], ['Document date', date(line.documentDate)], ['Supplier', `${line.supplier} · ${line.supplierName}`], ['Category', line.category],
        ['Plant / company', `${line.plant ?? '–'} / ${line.companyCode ?? '–'}`], ['Cost object', line.costObject ?? '–'],
        [`Amount (${line.currency})`, (line.amountMinor / 100).toLocaleString('en-IN')], [`Amount (${groupCurrency})`, inr(line.amountGroupMinor ?? line.amountMinor)],
        ['FX rate', line.fxRate ?? '–'], ['Source', `${label(line.source)}${line.sourceSystem ? ` · ${line.sourceSystem}` : ''}`],
        ['Price variance', inr(line.priceVarianceMinor)], ['Addressable', line.addressable ? 'Yes' : 'No'],
      ]} />
      <div className="mt-4 flex justify-end"><Button onClick={onClose}>Close</Button></div>
    </Dialog>
  );
}

function ExportCard({ filters }: { filters: Filters }) {
  const toast = useToast();
  const [kind, setKind] = useState<'lines' | 'cube'>('lines');
  const [dims, setDims] = useState('category');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const q = toQuery(filters, { kind, ...(kind === 'cube' ? { dims } : {}) });
      const response = await fetch(`/api/pic/v1/spend/export?${q}`, { cache: 'no-store' });
      if (!response.ok) {
        const problem = await response.json().catch(() => ({}));
        throw new ApiError({ status: response.status, code: problem.code ?? 'ERROR', ...problem });
      }
      const buffer = await response.arrayBuffer();
      const header = response.headers.get('x-content-sha256') ?? '';
      const actual = await sha256Hex(buffer);
      const name = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? `spend-${kind}.csv`;
      const url = URL.createObjectURL(new Blob([buffer], { type: 'text/csv' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = name;
      link.click();
      URL.revokeObjectURL(url);
      setResult({ fileName: name, rows: Number(response.headers.get('x-row-count') ?? 0), truncated: response.headers.get('x-truncated') === 'true', sha256: header,
        verified: actual && header ? actual === header : null, bytes: buffer.byteLength, kind });
      toast.success(`${name} exported`);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Export CSV" actions={<span className="text-xs text-slate-500">uses the filters above</span>}>
      <div className="grid gap-3 md:grid-cols-4">
        <Field label="What to export">{(id) => <Select id={id} value={kind} onChange={(e) => setKind(e.target.value as 'lines' | 'cube')}
          options={[{ value: 'lines', label: 'Spend lines (one row per line)' }, { value: 'cube', label: 'Cube slice (one row per combination)' }]} />}</Field>
        {kind === 'cube' && <Field label="Dimensions" hint="Comma-separated, e.g. category,supplier">{(id, d) => <Input id={id} aria-describedby={d} value={dims} onChange={(e) => setDims(e.target.value.replace(/\s/g, ''))} />}</Field>}
        <div className="flex items-end"><Button variant="primary" busy={busy} onClick={run}>Export CSV</Button></div>
      </div>
      <p className="mt-3 text-xs text-slate-600">
        The file is capped at the tenant’s export limit (rule <span className="font-mono">exportMaxRows</span>, default 50,000 rows). Every export is audited with your user, the filter, the row count and the
        file’s SHA-256, and cells that start with a formula character are neutralised.
      </p>
      {error && <div className="mt-3"><ProblemBox error={error} /></div>}
      {result && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4" role="status" data-testid="export-result">
          <p className="text-sm font-semibold text-slate-900">{result.fileName}</p>
          <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm md:grid-cols-3">
            <div><dt className="text-xs text-slate-500">Rows</dt><dd className="font-medium">{result.rows.toLocaleString('en-IN')}{result.truncated ? ' (cut at the row cap)' : ''}</dd></div>
            <div><dt className="text-xs text-slate-500">Size</dt><dd className="font-medium">{result.bytes.toLocaleString('en-IN')} bytes</dd></div>
            <div><dt className="text-xs text-slate-500">Integrity</dt><dd className="font-medium">{result.verified === null ? 'not checked' : result.verified ? 'hash matches the downloaded file' : 'HASH MISMATCH'}</dd></div>
          </dl>
          <p className="mt-2 break-all font-mono text-xs text-slate-700"><span className="text-slate-500">SHA-256 </span>{result.sha256 || 'not provided'}</p>
          {result.truncated && <p className="mt-2 text-xs font-medium text-amber-800">This file stops at the export row cap; narrow the filters to export the rest.</p>}
        </div>
      )}
    </Card>
  );
}
