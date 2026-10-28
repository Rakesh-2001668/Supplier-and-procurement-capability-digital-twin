'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function ViewInventoryRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/inventory');
  }, [router]);
  return null;
}
