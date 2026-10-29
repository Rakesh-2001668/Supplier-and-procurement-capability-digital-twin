'use client';

import { useSyncExternalStore } from 'react';
import { readSessionUser } from '@/lib/pic/api';

// Role hint for showing supplier-manager actions. Read from the display cookie after hydration (the server renders
// without it); the API still authorises every command.

const noSubscription = () => () => {};

function rolesSnapshot(): string {
  const user = readSessionUser();
  return user ? user.roles.join(',') : '-';
}

/** True when the signed-in user is a supplier manager (or the profile cookie is missing); false while hydrating. */
export function useSupplierManager(): boolean {
  const raw = useSyncExternalStore(noSubscription, rolesSnapshot, () => '');
  if (raw === '') return false;
  return raw === '-' || raw.split(',').includes('SUPPLIER_MANAGER');
}

/** True for a supplier manager or quality inspector: the roles that verify certificates (F8-04). */
export function useCertificateVerifier(): boolean {
  const raw = useSyncExternalStore(noSubscription, rolesSnapshot, () => '');
  if (raw === '') return false;
  return raw === '-' || raw.split(',').some((r) => r === 'SUPPLIER_MANAGER' || r === 'QUALITY_INSPECTOR');
}
