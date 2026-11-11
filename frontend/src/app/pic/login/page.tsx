'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useEffect, useState } from 'react';
import { Building2, Factory } from 'lucide-react';
import { ApiError, SessionUser } from '@/lib/pic/api';
import { Button, Input, ProblemBox } from '@/components/pic/ui';
import { AuthenticatorSetup, Enrolment } from '../account/_authenticator';
import { safeNext } from '@/lib/pic/nextPath';

// One sign-in for the whole platform (buyers and suppliers): e-mail and password; the organisation is found from the e-mail.
// A person in several organisations picks one (and can switch later from the header). MFA and single sign-on stay.

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

type Step = 'password' | 'choose' | 'mfa' | 'enrol';
type Organisation = { code: string; name: string; kind: 'BUYER' | 'SUPPLIER'; roles: string[]; supplierUser: boolean };
type StepAnswer = { user?: SessionUser; mfaRequired?: boolean; organisationChoice?: boolean; organisations?: Organisation[] };

async function post<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...data });
  return data as T;
}

function roleText(roles: string[]): string {
  return roles.map((r) => r.replace(/_/g, ' ').toLowerCase()).join(', ');
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState('buyer@axion.example');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<Step>(params.get('step') === 'mfa' ? 'mfa' : 'password');
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [ssoTenant, setSsoTenant] = useState<string | null>(null);
  const ssoError = params.get('sso');

  // Single sign-on is offered when the e-mail's domain belongs to an organisation that signs in with its identity provider.
  useEffect(() => {
    const value = email.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/pic/v1/auth/sso?email=${encodeURIComponent(value)}`, { cache: 'no-store' });
        const data = await response.json();
        if (!cancelled) setSsoTenant(data?.enabled ? String(data.tenant) : null);
      } catch {
        if (!cancelled) setSsoTenant(null);
      }
    }, 400);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [email]);

  function done(user: SessionUser) {
    const fallback = user.roles.includes('PLATFORM_OPERATOR') ? '/pic/platform/registrations'
      : user.roles.includes('SUPPLIER_USER') ? '/pic/portal' : '/pic';
    const next = params.get('next');
    router.replace(next && safeNext(next) ? next : fallback);
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      if ((err as ApiError).problem?.code === 'MFA_ENROLMENT_REQUIRED') {
        setStep('enrol');
        return;
      }
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  function next(answer: StepAnswer) {
    if (answer.organisationChoice) {
      setOrganisations(answer.organisations ?? []);
      setStep('choose');
      return;
    }
    if (answer.mfaRequired) {
      setCode('');
      setStep('mfa');
      return;
    }
    if (answer.user) done(answer.user);
  }

  function submitPassword(e: FormEvent) {
    e.preventDefault();
    run(async () => next(await post<StepAnswer>('/api/auth/login', { email: email.trim().toLowerCase(), password })));
  }

  function choose(organisation: string) {
    run(async () => next(await post<StepAnswer>('/api/auth/organisation', { organisation })));
  }

  function submitCode(e: FormEvent) {
    e.preventDefault();
    run(async () => done((await post<{ user: SessionUser }>('/api/auth/mfa', { code })).user));
  }

  function startEnrolment() {
    run(async () => setEnrolment(await post<Enrolment>('/api/auth/mfa/enrol', { action: 'start' })));
  }

  function confirmEnrolment(value: string) {
    run(async () => done((await post<{ user: SessionUser }>('/api/auth/mfa/enrol', { action: 'confirm', code: value })).user));
  }

  function restart() {
    setStep('password');
    setEnrolment(null);
    setOrganisations([]);
    setCode('');
    setError(null);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0B1020] px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-[#1A56DB] text-xl font-bold text-white">α</span>
          <h1 className="mt-3 text-xl font-semibold text-white">AlphaHelion Purchasing Intelligence Cloud</h1>
          <p className="text-sm text-slate-400">One sign-in for buyers and suppliers</p>
        </div>

        {step === 'password' && (
          <form onSubmit={submitPassword} className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
            <div className="space-y-1">
              <label htmlFor="email" className="text-xs font-medium text-slate-700">Work e-mail</label>
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
            {ssoTenant && (
              <>
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-slate-400">
                  <span className="h-px flex-1 bg-slate-200" />or<span className="h-px flex-1 bg-slate-200" />
                </div>
                <a href={`/api/auth/oidc/start?tenant=${encodeURIComponent(ssoTenant)}&next=${encodeURIComponent(params.get('next') ?? '')}`}
                  className="flex w-full items-center justify-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50">
                  Continue with single sign-on
                </a>
              </>
            )}
            <p className="text-center text-xs text-slate-600">
              New to the platform? <a href="/register" className="font-medium text-[#1A56DB] hover:underline">Register your organisation</a>
            </p>
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

        {step === 'choose' && (
          <div className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Choose an organisation</h2>
              <p className="mt-1 text-sm text-slate-600">{email} has an account in more than one organisation. You can switch later from the header.</p>
            </div>
            <ul className="space-y-2">
              {organisations.map((o) => {
                const Icon = o.kind === 'SUPPLIER' || o.supplierUser ? Factory : Building2;
                return (
                  <li key={o.code}>
                    <button type="button" disabled={busy} onClick={() => choose(o.code)}
                      className="flex w-full items-center gap-3 rounded-lg border border-slate-200 px-3 py-2.5 text-left hover:border-[#1A56DB] hover:bg-slate-50 disabled:opacity-60">
                      <Icon size={20} className="shrink-0 text-[#1A56DB]" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-900">{o.name}</span>
                        <span className="block truncate text-xs text-slate-500">
                          {o.code} · {o.kind === 'SUPPLIER' ? 'Supplier' : 'Buyer'} organisation · {roleText(o.roles)}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <ProblemBox error={error} />
            <button type="button" onClick={restart} className="w-full text-center text-xs text-slate-500 hover:text-slate-800">Use a different account</button>
          </div>
        )}

        {step === 'mfa' && (
          <form onSubmit={submitCode} className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Two-step verification</h2>
              <p className="mt-1 text-sm text-slate-600">Enter the 6-digit code from your authenticator app.</p>
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
