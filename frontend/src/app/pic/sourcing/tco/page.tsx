'use client';

import { Card, LinkButton, PageHeader } from '@/components/pic/ui';
import { MANAGE_ROLES, useCan } from '../_lib';
import { TcoSimulator } from '../_tco';

export default function TcoPage() {
  const can = useCan();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="SRC-03 · TCO" title="TCO simulator" actions={<LinkButton href="/pic/sourcing">Back to sourcing</LinkButton>}
        subtitle="Try a bid line against the SOURCING-TCO rule before an event exists: the cost stack with the status of every component." />
      <Card>{can(MANAGE_ROLES) ? <TcoSimulator /> : <p className="text-sm text-slate-600">The simulator is for buyers and category managers (permission sourcing:manage).</p>}</Card>
    </div>
  );
}
