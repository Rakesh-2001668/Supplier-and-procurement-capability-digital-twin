'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import InvoicesPage from '@/app/invoices/page';

export default function BuyerInvoicesForwarder() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/invoices');
  }, [router]);

  return <InvoicesPage />;
}
