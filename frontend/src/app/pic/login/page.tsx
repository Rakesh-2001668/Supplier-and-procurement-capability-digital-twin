'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useState } from 'react';
import { ApiError, signIn } from '@/lib/pic/api';
import { Button, Input, ProblemBox } from '@/components/pic/ui';

const DEMO = [
  ['buyer', 'Buyer'], ['requester', 'Requester'], ['plant.controller', 'Cost-object owner'], ['category.manager', 'Category manager'],
  ['mrp.controller', 'MRP controller'], ['receiver', 'Receiver'], ['quality.inspector', 'Quality'], ['ap.clerk', 'AP clerk'],
  ['finance.controller', 'Finance controller'], ['cpo', 'CPO'], ['admin', 'Tenant admin'], ['tf.sales', 'Supplier: Trichy Forge'],
];

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [tenant, setTenant] = useState('AXN');
  const [email, setEmail] = useState('buyer@axion.example');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await signIn(tenant.trim(), email.trim().toLowerCase(), password);
      const fallback = user.roles.includes('SUPPLIER_USER') ? '/pic/portal' : '/pic';
      const next = params.get('next');
      router.replace(next && next.startsWith('/pic') && !next.startsWith('/pic/login') ? next : fallback);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0B1020] px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-[#1A56DB] text-xl font-bold text-white">α</span>
          <h1 className="mt-3 text-xl font-semibold text-white">Purchasing Intelligence Cloud</h1>
          <p className="text-sm text-slate-400">AI recommends. Humans decide.</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
          <div className="space-y-1">
            <label htmlFor="tenant" className="text-xs font-medium text-slate-700">Organisation code</label>
            <Input id="tenant" value={tenant} onChange={(e) => setTenant(e.target.value)} autoComplete="organization" required />
          </div>
          <div className="space-y-1">
            <label htmlFor="email" className="text-xs font-medium text-slate-700">Work email</label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
          </div>
          <div className="space-y-1">
            <label htmlFor="password" className="text-xs font-medium text-slate-700">Password</label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </div>
          <ProblemBox error={error} />
          <Button type="submit" variant="primary" busy={busy} className="w-full py-2">Sign in</Button>
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer select-none">Demo users (Axion Mobility)</summary>
            <div className="mt-2 grid grid-cols-2 gap-1">
              {DEMO.map(([local, role]) => (
                <button type="button" key={local} onClick={() => setEmail(`${local}@axion.example`)}
                  className="rounded border border-slate-200 px-2 py-1 text-left hover:bg-slate-50">{role}</button>
              ))}
            </div>
          </details>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
