'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { KeyboardEvent, ReactNode, Suspense, useId, useRef, useState } from 'react';
import { Loading, PageHeader } from '@/components/pic/ui';
import { CategoriesTab } from './_components/categories';
import { ClassificationTab } from './_components/classification';
import { CompareTab } from './_components/compare';
import { ComplianceTab } from './_components/compliance';
import { CubeTab } from './_components/cube';
import { DuplicatesTab } from './_components/duplicates';
import { ForecastTab } from './_components/forecast';
import { LinesTab } from './_components/lines';
import { MaverickTab } from './_components/maverick';
import { OverviewTab } from './_components/overview';
import { ParetoTab } from './_components/pareto';
import { QualityTab } from './_components/quality';
import { StrategyTab } from './_components/strategy';
import { SuppliersTab } from './_components/suppliers';

type TabDef = { id: string; label: string; render: () => ReactNode };
type Group = { id: string; label: string; tabs: TabDef[] };

// Two levels keep the bar short at phone width. The URL carries the leaf (`?tab=compliance`), so every earlier deep link still opens the right view.
const GROUPS: Group[] = [
  { id: 'overview', label: 'Overview', tabs: [
    { id: 'overview', label: 'Overview (SPD-01)', render: () => <OverviewTab /> },
    { id: 'compare', label: 'Fiscal year and comparisons', render: () => <CompareTab /> },
  ] },
  { id: 'analysis', label: 'Analysis', tabs: [
    { id: 'categories', label: 'Categories (SPD-02)', render: () => <CategoriesTab /> },
    { id: 'suppliers', label: 'Suppliers (SPD-03)', render: () => <SuppliersTab /> },
    { id: 'pareto', label: 'Pareto, tail and savings', render: () => <ParetoTab /> },
    { id: 'cube', label: 'Cube (SPD-04)', render: () => <CubeTab /> },
    { id: 'lines', label: 'Lines and export', render: () => <LinesTab /> },
  ] },
  { id: 'governance', label: 'Governance', tabs: [
    { id: 'compliance', label: 'Contract compliance (SPD-05)', render: () => <ComplianceTab /> },
    { id: 'maverick', label: 'Maverick (SPD-06)', render: () => <MaverickTab /> },
    { id: 'classification', label: 'Classification and taxonomy', render: () => <ClassificationTab /> },
    { id: 'duplicates', label: 'Duplicate suppliers', render: () => <DuplicatesTab /> },
    { id: 'quality', label: 'Data quality', render: () => <QualityTab /> },
  ] },
  { id: 'planning', label: 'Planning', tabs: [
    { id: 'strategy', label: 'Category strategy (SPD-07)', render: () => <StrategyTab /> },
    { id: 'forecast', label: 'Forecast (SPD-09)', render: () => <ForecastTab /> },
  ] },
];
const ALL_TABS = GROUPS.flatMap((g) => g.tabs);

/** Roving-tabindex arrow/Home/End handling shared by both tab levels. */
function arrowTo(e: KeyboardEvent<HTMLButtonElement>, index: number, count: number): number {
  const move = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
  const to = e.key === 'Home' ? 0 : e.key === 'End' ? count - 1 : move ? (index + move + count) % count : -1;
  if (to >= 0) e.preventDefault();
  return to;
}

/**
 * Two-level tabs with the same look as the shared Tabs: the area (overview, analysis, governance, planning) and the view inside it.
 * The active view lives in `?tab=` so deep links (e.g. opportunities pointing at /pic/spend?tab=compliance) open the right view.
 */
function SpendWorkspace() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const base = useId();
  const groupRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const requested = params.get('tab');
  // The selection is applied at once and mirrored to the URL: a navigation can take a moment, and a keyboard user must not wait for it.
  const [chosen, setChosen] = useState<{ id: string; from: string | null } | null>(null);
  const shown = chosen && chosen.from === requested ? chosen.id : requested;
  const active = ALL_TABS.find((t) => t.id === shown) ?? ALL_TABS[0];
  const group = GROUPS.find((g) => g.tabs.some((t) => t.id === active.id)) ?? GROUPS[0];

  function select(id: string) {
    setChosen({ id, from: requested });
    router.replace(`${pathname}?tab=${encodeURIComponent(id)}`, { scroll: false });
  }

  return (
    <div>
      <div role="tablist" aria-label="Spend areas" className="flex flex-wrap gap-1 border-b border-slate-200">
        {GROUPS.map((g, i) => {
          const on = g.id === group.id;
          return (
            <button key={g.id} ref={(el) => { groupRefs.current[i] = el; }} id={`${base}-group-${g.id}`} role="tab" type="button" aria-selected={on} aria-controls={`${base}-views`}
              tabIndex={on ? 0 : -1}
              onClick={() => select(g.tabs[0].id)}
              onKeyDown={(e) => { const to = arrowTo(e, i, GROUPS.length); if (to >= 0) { groupRefs.current[to]?.focus(); select(GROUPS[to].tabs[0].id); } }}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] ${on ? 'border-[#1A56DB] text-[#1A56DB]' : 'border-transparent text-slate-600 hover:text-slate-900'}`}>
              {g.label}
            </button>
          );
        })}
      </div>
      <div id={`${base}-views`} role="tablist" aria-label={`${group.label} views`} className="flex flex-wrap gap-1 pt-2">
        {group.tabs.map((t, i) => {
          const on = t.id === active.id;
          return (
            <button key={t.id} ref={(el) => { tabRefs.current[i] = el; }} id={`${base}-tab-${t.id}`} role="tab" type="button" aria-selected={on} aria-controls={`${base}-panel`}
              tabIndex={on ? 0 : -1}
              onClick={() => select(t.id)}
              onKeyDown={(e) => { const to = arrowTo(e, i, group.tabs.length); if (to >= 0) { tabRefs.current[to]?.focus(); select(group.tabs[to].id); } }}
              className={`rounded-full px-3 py-1 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1A56DB] ${on ? 'bg-blue-50 text-[#1A56DB] ring-1 ring-inset ring-blue-200' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}`}>
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
      <PageHeader kpis="M01" eyebrow="SPD-01..09 · Spend governance" title="Spend analysis"
        subtitle="Spend from posted invoice lines and the notes that correct them: where it goes, who it goes to, how much is on contract, what breaks policy and where the category strategy should take it. Amounts are in rupees; shares are of addressable spend." />
      <Suspense fallback={<Loading />}>
        <SpendWorkspace />
      </Suspense>
    </div>
  );
}
