'use client';

import { Button, Dialog } from '@/components/pic/ui';
import { EarlyPaymentPanel } from '../invoices/_p2p';

/** Supplier portal: the early-payment offers, requests and supply-chain-finance election of one invoice. */
export function EarlyPaymentDialog({ invoiceId, onClose }: { invoiceId: string; onClose: () => void }) {
  return (
    <Dialog open title="Early payment and supply-chain finance" onClose={onClose}>
      <EarlyPaymentPanel invoiceId={invoiceId} />
      <div className="mt-4 flex justify-end"><Button onClick={onClose}>Close</Button></div>
    </Dialog>
  );
}
