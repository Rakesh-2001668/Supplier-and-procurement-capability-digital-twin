'use client';

import { Card, Empty, Kpi, Loading, PageHeader, ProblemBox, StatusChip, Tabs } from '@/components/pic/ui';
import { inr, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { useMe } from '../mrp/_components';
import { KanbanPanel, ParameterPanel, SelfBillingPanel } from './_manufacturing';
import { AdvancePanel, GuaranteePanel, LicencePanel } from './_projects';
import { AccessorialPanel, ColdChainPanel, IndexPanel, PCardPanel, ParLevelPanel } from './_ops';

export type Controls = { template: string; controls: Record<string, { enabled: boolean; rule: string | null; title: string }> };
type KpiItem = { code: string; name: string; unit: string; value: string | null; status: string; detail: Record<string, unknown> };

/** Industry-template controls (blueprint §23): only the controls the tenant's template carries are offered. */
export default function IndustryPage() {
  const controls = useApi<Controls>('/industry/controls');
  const { scopes } = useMe();
  if (controls.isLoading) return <Loading />;
  if (controls.error || !controls.data) return <ProblemBox error={controls.error} />;
  const on = (name: string) => controls.data.controls[name]?.enabled;
  const tabs = [
    on('kanban') && { id: 'kanban', label: 'Kanban & reorder point', content: <><KanbanPanel canPlan={scopes.includes('mrp:plan')} /><ParameterPanel canPlan={scopes.includes('mrp:plan')} /></> },
    on('selfBilling') && { id: 'ers', label: 'Self-billing (ERS)', content: <SelfBillingPanel canSettle={scopes.includes('invoice:post') || scopes.includes('payment:run')} /> },
    on('advancePayment') && { id: 'advances', label: 'Advances', content: <AdvancePanel canRequest={scopes.includes('contract:manage') || scopes.includes('invoice:post')} /> },
    on('bankGuarantee') && { id: 'guarantees', label: 'Bank guarantees', content: <GuaranteePanel scopes={scopes} /> },
    on('licences') && { id: 'licences', label: 'Licences', content: <LicencePanel canManage={scopes.includes('sourcing:manage') || scopes.includes('contract:manage')} /> },
    on('accessorials') && { id: 'accessorials', label: 'Accessorial charges', content: <><AccessorialPanel scopes={scopes} /><IndexPanel canFeed={scopes.includes('contract:manage')} /></> },
    on('coldChain') && { id: 'cold', label: 'Cold chain & expiry', content: <ColdChainPanel scopes={scopes} /> },
    on('parLevels') && { id: 'par', label: 'Par levels & VAC', content: <ParLevelPanel canPlan={scopes.includes('mrp:plan')} /> },
    on('pcards') && { id: 'pcards', label: 'Purchasing cards', content: <PCardPanel scopes={scopes} /> },
  ].filter(Boolean) as { id: string; label: string; content: React.ReactNode }[];
  return (
    <div className="space-y-5">
      <PageHeader eyebrow={`Industry template · ${label(controls.data.template)}`} title="Industry controls"
        subtitle="Controls the tenant's industry template switches on through its rule sets; everything else stays hidden." />
      <IndustryKpis />
      {tabs.length ? <Card><Tabs tabs={tabs} /></Card> : <Empty title="No industry controls are enabled" hint="The tenant's template carries none of them." />}
    </div>
  );
}

function IndustryKpis() {
  const kpis = useApi<{ kpis: KpiItem[] }>('/industry/kpis');
  if (!kpis.data?.kpis.length) return null;
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {kpis.data.kpis.map((k) => (
        <Kpi key={k.code} label={k.name} tone={k.status === 'GOOD' ? 'good' : k.status === 'WARN' ? 'warn' : k.status === 'BAD' ? 'bad' : 'default'}
          value={k.value == null ? '–' : k.unit === 'MINOR' ? inr(Number(k.value)) : `${k.value}${k.unit === 'PCT' ? '%' : ''}`}
          hint={<StatusChip status={k.status === 'NA' ? 'PENDING' : k.status} />} />
      ))}
    </div>
  );
}
