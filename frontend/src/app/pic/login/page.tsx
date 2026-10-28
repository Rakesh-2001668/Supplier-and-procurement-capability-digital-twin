'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useEffect, useState } from 'react';
import { ApiError, SessionUser } from '@/lib/pic/api';
import { Button, Input, ProblemBox } from '@/components/pic/ui';
import { AuthenticatorSetup, Enrolment } from '../account/_authenticator';

const DEMO = [
  ['buyer', 'Buyer'], ['requester', 'Requester'], ['plant.controller', 'Cost-object owner'], ['category.manager', 'Category manager'],
  ['mrp.controller', 'MRP controller'], ['receiver', 'Receiver'], ['quality.inspector', 'Quality'], ['ap.clerk', 'AP clerk'],
  ['finance.controller', 'Finance controller'], ['cpo', 'CPO'], ['admin', 'Tenant admin'], ['tf.sales', 'Supplier: Trichy Forge'],
];

const SSO_ERRORS: Record<string, string> = {
  OIDC_NOT_CONFIGURED: 'Single sign-on is not set up for this organisation.',
  OIDC_STATE_INVALID: 'The single sign-on attempt expired or was started in another browser. Try again.',
  OIDC_USER_UNKNOWN: 'Your identity provider account has no active user in this organisation. Ask your administrator.',
  OIDC_TOKEN_INVALID: 'The identity provider response could not be verified.',
  OIDC_TOKEN_EXPIRED: 'The identity provider response has expired. Try again.',
  IDP_MFA_REQUIRED: 'Your role requires multi-factor authentication at your identity provider.',
  IDP_ACCESS_DENIED: 'Sign-in was cancelled at the identity provider.',
};

type Step = 'password' | 'mfa' | 'enrol';

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...data });
  return data as T;
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [tenant, setTenant] = useState('AXN');
  const [email, setEmail] = useState('buyer@axion.example');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<Step>('password');
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [sso, setSso] = useState(false);
  const ssoError = params.get('sso');

  useEffect(() => {
    const code_ = tenant.trim().toUpperCase();
    if (!/^[A-Z0-9_]{2,20}$/.test(code_)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/pic/v1/auth/oidc/${encodeURIComponent(code_)}`, { cache: 'no-store' });
        const data = await response.json();
        if (!cancelled) setSso(!!data?.enabled);
      } catch {
        if (!cancelled) setSso(false);
      }
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [tenant]);

  function done(user: SessionUser) {
    const fallback = user.roles.includes('SUPPLIER_USER') ? '/pic/portal' : '/pic';
    const next = params.get('next');
    router.replace(next && next.startsWith('/pic') && !next.startsWith('/pic/login') ? next : fallback);
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  function submitPassword(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      try {
        const data = await post<{ user?: SessionUser; mfaRequired?: boolean }>('/api/auth/login',
          { tenant: tenant.trim(), email: email.trim().toLowerCase(), password });
        if (data.mfaRequired) {
          setCode('');
          setStep('mfa');
          return;
        }
        if (data.user) done(data.user);
      } catch (err) {
        if ((err as ApiError).problem?.code === 'MFA_ENROLMENT_REQUIRED') {
          setStep('enrol');
          return;
        }
        throw err;
      }
    });
  }

  function submitCode(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      const data = await post<{ user: SessionUser }>('/api/auth/mfa', { code });
      done(data.user);
    });
  }

  function startEnrolment() {
    run(async () => setEnrolment(await post<Enrolment>('/api/auth/mfa/enrol', { action: 'start' })));
  }

  function confirmEnrolment(value: string) {
    run(async () => {
      const data = await post<{ user: SessionUser }>('/api/auth/mfa/enrol', { action: 'confirm', code: value });
      done(data.user);
    });
  }

  function restart() {
    setStep('password');
    setEnrolment(null);
    setCode('');
    setError(null);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0B1020] px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-[#1A56DB] text-xl font-bold text-white">α</span>
          <h1 className="mt-3 text-xl font-semibold text-white">Purchasing Intelligence Cloud</h1>
          <p className="text-sm text-slate-400">AI recommends. Humans decide.</p>
        </div>

        {step === 'password' && (
          <form onSubmit={submitPassword} className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
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
            {ssoError && (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
                {SSO_ERRORS[ssoError] ?? `Single sign-on failed (${ssoError}).`}
              </div>
            )}
            <ProblemBox error={error} />
            <Button type="submit" variant="primary" busy={busy} className="w-full py-2">Sign in</Button>
            {sso && (
              <>
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-slate-400">
                  <span className="h-px flex-1 bg-slate-200" />or<span className="h-px flex-1 bg-slate-200" />
                </div>
                <a href={`/api/auth/oidc/start?tenant=${encodeURIComponent(tenant.trim().toUpperCase())}&next=${encodeURIComponent(params.get('next') ?? '')}`}
                  className="flex w-full items-center justify-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50">
                  Sign in with SSO
                </a>
              </>
            )}
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
        )}

        {step === 'mfa' && (
          <form onSubmit={submitCode} className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Two-step verification</h2>
              <p className="mt-1 text-sm text-slate-600">Enter the 6-digit code from the authenticator app registered for {email}.</p>
            </div>
            <div className="space-y-1">
              <label htmlFor="code" className="text-xs font-medium text-slate-700">Authentication code</label>
              <Input id="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength={8} autoFocus required
                value={code} onChange={(e) => setCode(e.target.value)} className="font-mono tracking-[0.3em]" />
            </div>
            <ProblemBox error={error} />
            <Button type="submit" variant="primary" busy={busy} className="w-full py-2">Verify</Button>
            <button type="button" onClick={restart} className="w-full text-center text-xs text-slate-500 hover:text-slate-800">Use a different account</button>
          </form>
        )}

        {step === 'enrol' && (
          <div className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Set up two-step verification</h2>
              <p className="mt-1 text-sm text-slate-600">
                Your role requires multi-factor authentication. Register an authenticator app (Microsoft Authenticator, Google Authenticator,
                1Password or similar) to finish signing in.
              </p>
            </div>
            {enrolment ? (
              <AuthenticatorSetup enrolment={enrolment} busy={busy} onConfirm={confirmEnrolment} />
            ) : (
              <Button variant="primary" busy={busy} className="w-full py-2" onClick={startEnrolment}>Set up authenticator</Button>
            )}
            <ProblemBox error={error} />
            <button type="button" onClick={restart} className="w-full text-center text-xs text-slate-500 hover:text-slate-800">Back to sign-in</button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
