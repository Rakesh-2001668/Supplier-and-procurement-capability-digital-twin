'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function AddInventoryRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/inventory/create');
  }, [router]);
  return null;
}
