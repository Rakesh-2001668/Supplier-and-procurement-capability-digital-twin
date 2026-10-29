'use client';

import { useParams } from 'next/navigation';
import { LinkButton, Loading, PageHeader, ProblemBox } from '@/components/pic/ui';
import { useApi } from '@/lib/pic/hooks';
import { hasRole, useSessionUser } from '../../../../invoices/_components';
import { LotTrace, LotTraceView } from '../../../_special';

export default function LotTracePage() {
  const params = useParams<{ material: string; batch: string }>();
  const material = decodeURIComponent(params.material);
  const batch = decodeURIComponent(params.batch);
  const user = useSessionUser();
  const { data, isLoading, error } = useApi<LotTrace>(`/lots/${encodeURIComponent(material)}/${encodeURIComponent(batch)}/trace`);
  return (
    <div>
      <PageHeader eyebrow="RCV-05 · Lot traceability" title={<>{material} <span className="text-base font-normal text-slate-500">lot {batch}</span></>}
        subtitle={data ? `${data.description}${data.suppliers.length ? ` · supplied by ${data.suppliers.join(', ')}` : ''}` : undefined}
        actions={<LinkButton href="/pic/receiving">Receiving</LinkButton>} />
      {isLoading ? <Loading /> : error ? <ProblemBox error={error} /> : data && (
        <LotTraceView trace={data} canRecall={hasRole(user, 'QUALITY_INSPECTOR')} />
      )}
    </div>
  );
}
