'use client';

import { Card, LinkButton, Loading, PageHeader, Tabs } from '@/components/pic/ui';
import { hasRole, useSessionUser } from '../_components';
import { ChallansTab, Form16ATab, MsmeTab, RegisterTab } from '../_tax';

export default function TaxCompliance() {
  const user = useSessionUser();
  const finance = hasRole(user, 'FINANCE_CONTROLLER');
  // The tab list depends on the role, which is read from the cookie after hydration; the first tab is chosen when Tabs mounts, so wait for it.
  if (user === undefined) return <Loading />;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="INV-05 · TDS, Form 16A and MSME" title="TDS, Form 16A & MSME interest"
        subtitle="TDS deducted from supplier payments against the challans that deposit it, the Form 16A data of each deductee and quarter, the TDS register and return export, and the interest owed on late payments to MSME suppliers."
        actions={<>
          <LinkButton href="/pic/invoices">Invoices</LinkButton>
          <LinkButton href="/pic/invoices/reconciliation">Posting & reconciliation</LinkButton>
        </>} />
      <Card>
        <Tabs label="Tax and MSME sections" tabs={[
          ...(finance ? [
            { id: 'challans', label: 'Challans & reconciliation', content: <ChallansTab /> },
            { id: '16a', label: 'Form 16A data', content: <Form16ATab /> },
          ] : []),
          { id: 'register', label: 'TDS register & return', content: <RegisterTab /> },
          { id: 'msme', label: 'MSME interest', content: <MsmeTab /> },
        ]} />
      </Card>
    </div>
  );
}
