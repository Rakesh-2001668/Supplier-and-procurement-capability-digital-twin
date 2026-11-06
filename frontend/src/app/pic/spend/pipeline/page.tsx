'use client';

import { Suspense } from 'react';
import { Loading, PageHeader } from '@/components/pic/ui';
import { PipelineTab } from '../_components/pipeline';

export default function SavingsPipelinePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        kpis="M11"
        eyebrow="SPD-08 · Spend governance & value realisation"
        title="Savings pipeline tracker"
        subtitle="Forecast vs realised savings and cost avoidance across initiatives and stages: from identified opportunities through negotiation, contracting, line-item realization on invoices, to finance validation and P&L budget impact."
      />
      <Suspense fallback={<Loading />}>
        <PipelineTab />
      </Suspense>
    </div>
  );
}

