'use client';

import { Card, PageHeader, Tabs } from '@/components/pic/ui';
import { AlertsTab, MovementsTab, StockTab } from './_stock';
import { PostingsTab } from './_postings';
import { CountsTab } from './_counts';
import { ReservationsTab } from './_reservations';
import { useRules } from './_shared';

export default function Inventory() {
  const rules = useRules();
  const me = rules.data?.me;
  return (
    <div>
      <PageHeader eyebrow="INV-01 · Inventory" title="Inventory"
        subtitle="Stock by plant, location, type and batch; alerts; the movement ledger; governed stock postings, blind physical inventory and reservations. Stock changes only through postings, counts and goods movements." />
      <Card>
        <Tabs label="Inventory sections" tabs={[
          { id: 'stock', label: 'Stock', content: <StockTab /> },
          { id: 'alerts', label: 'Alerts', content: <AlertsTab /> },
          { id: 'movements', label: 'Movements', content: <MovementsTab /> },
          { id: 'postings', label: 'Postings', content: <PostingsTab canPost={!!me?.canPost} /> },
          { id: 'counts', label: 'Counts', content: <CountsTab canCreate={!!me && (me.canPost || me.canCount)} /> },
          { id: 'reservations', label: 'Reservations', content: <ReservationsTab canPost={!!me?.canPost} /> },
        ]} />
      </Card>
    </div>
  );
}
