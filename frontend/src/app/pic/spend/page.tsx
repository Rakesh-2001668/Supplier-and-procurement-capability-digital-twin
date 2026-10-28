'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { KeyboardEvent, ReactNode, Suspense, useId, useRef } from 'react';
import { Loading, PageHeader } from '@/components/pic/ui';
import { CategoriesTab } from './_components/categories';
import { ClassificationTab } from './_components/classification';
import { ComplianceTab } from './_components/compliance';
import { CubeTab } from './_components/cube';
import { ForecastTab } from './_components/forecast';
import { MaverickTab } from './_components/maverick';
import { OverviewTab } from './_components/overview';
import { StrategyTab } from './_components/strategy';
import { SuppliersTab } from './_components/suppliers';

const TABS: { id: string; label: string; render: () => ReactNode }[] = [
  { id: 'overview', label: 'Overview (SPD-01)', render: () => <OverviewTab /> },
  { id: 'categories', label: 'Categories (SPD-02)', render: () => <CategoriesTab /> },
  { id: 'suppliers', label: 'Suppliers (SPD-03)', render: () => <SuppliersTab /> },
  { id: 'cube', label: 'Cube (SPD-04)', render: () => <CubeTab /> },
  { id: 'compliance', label: 'Contract compliance (SPD-05)', render: () => <ComplianceTab /> },
  { id: 'maverick', label: 'Maverick (SPD-06)', render: () => <MaverickTab /> },
  { id: 'classification', label: 'Classification review', render: () => <ClassificationTab /> },
  { id: 'strategy', label: 'Category strategy (SPD-07)', render: () => <StrategyTab /> },
  { id: 'forecast', label: 'Forecast (SPD-09)', render: () => <ForecastTab /> },
];

/**
 * Same look as the shared Tabs, but the active tab lives in `?tab=` so deep links
 * (e.g. opportunities pointing at /pic/spend?tab=compliance) open the right view.
 */
function SpendWorkspace() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const requested = params.get('tab');
  const active = TABS.find((t) => t.id === requested) ?? TABS[0];

  function select(id: string) {
    const next = new URLSearchParams(params.toString());
    next.set('tab', id);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function onKey(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    const move = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    const to = e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : move ? (index + move + TABS.length) % TABS.length : -1;
    if (to < 0) return;
    e.preventDefault();
    refs.current[to]?.focus();
    select(TABS[to].id);
  }

  return (
    <div>
      <div role="tablist" aria-label="Spend analytics views" className="flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t, i) => {
          const on = t.id === active.id;
          return (
            <button key={t.id} ref={(el) => { refs.current[i] = el; }} id={`${base}-tab-${t.id}`} role="tab" type="button"
              aria-selected={on} aria-controls={`${base}-panel`} tabIndex={on ? 0 : -1}
              onClick={() => select(t.id)} onKeyDown={(e) => onKey(e, i)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${on ? 'border-[#1A56DB] text-[#1A56DB]' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="pt-4" role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-tab-${active.id}`}>
        {active.render()}
      </div>
    </div>
  );
}

export default function SpendAnalysis() {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="SPD-01..09 · Spend governance" title="Spend analysis"
        subtitle="Spend from posted invoice lines: where it goes, who it goes to, how much is on contract, what breaks policy and where the category strategy should take it. Amounts are in rupees; shares are of addressable spend." />
      <Suspense fallback={<Loading />}>
        <SpendWorkspace />
      </Suspense>
    </div>
  );
}
