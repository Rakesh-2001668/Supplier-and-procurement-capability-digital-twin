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
    <div className="grid min-h-screen bg-canvas lg:grid-cols-[1.05fr_1fr]">
      {/* Brand panel: keeps its dark design in both themes. */}
      <aside className="theme-fixed relative hidden overflow-hidden bg-[#0B1020] lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_380px_at_15%_10%,rgba(59,118,240,0.35),transparent_65%),radial-gradient(520px_360px_at_90%_85%,rgba(124,58,237,0.30),transparent_65%)]" />
        <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:linear-gradient(rgba(255,255,255,.6)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.6)_1px,transparent_1px)] [background-size:44px_44px]" />
        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#3B76F0] to-[#7C3AED] text-xl font-bold text-white shadow-lg shadow-blue-900/40">α</span>
          <span className="text-sm font-semibold tracking-tight text-white">AlphaHelion Cloud</span>
        </div>
        <div className="relative max-w-lg">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight text-white">
            Purchasing intelligence,<br />
            <span className="bg-gradient-to-r from-sky-300 via-blue-300 to-violet-300 bg-clip-text text-transparent">from plan to payment.</span>
          </h2>
          <p className="mt-4 text-base leading-relaxed text-slate-300">
            One platform for buyers and suppliers: sourcing, contracts, orders, receiving, invoices and supplier capability, with live data and controls built in.
          </p>
          <ul className="mt-8 grid grid-cols-2 gap-3 text-sm text-slate-200">
            {['Live spend & savings', 'Supplier capability twin', 'Three-way match', 'Audit-ready controls'].map((f) => (
              <li key={f} className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 backdrop-blur">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-gradient-to-br from-sky-300 to-violet-300" />{f}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-slate-500">© AlphaHelion · Purchasing Intelligence Cloud</p>
      </aside>

      <div className="relative flex items-center justify-center px-4 py-12">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-80 [background:var(--glow)]" />
      <div className="relative w-full max-w-md animate-rise">
        <div className="mb-7">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#3B76F0] to-[#7C3AED] text-xl font-bold text-white shadow-lg shadow-blue-900/30 lg:hidden">α</span>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-ink lg:mt-0">Sign in</h1>
          <p className="mt-1 text-sm text-ink-3">AlphaHelion Purchasing Intelligence Cloud · one sign-in for buyers and suppliers</p>
        </div>

        {step === 'password' && (
          <form onSubmit={submitPassword} className="space-y-4 rounded-2xl border border-line bg-surface p-7 shadow-raised">
            <div className="space-y-1">
              <label htmlFor="email" className="text-xs font-medium text-ink-2">Work e-mail</label>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
            </div>
            <div className="space-y-1">
              <label htmlFor="password" className="text-xs font-medium text-ink-2">Password</label>
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
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-ink-3">
                  <span className="h-px flex-1 bg-line" />or<span className="h-px flex-1 bg-line" />
                </div>
                <a href={`/api/auth/oidc/start?tenant=${encodeURIComponent(ssoTenant)}&next=${encodeURIComponent(params.get('next') ?? '')}`}
                  className="flex w-full items-center justify-center rounded-lg border border-line-strong px-3 py-2 text-sm font-medium text-ink hover:bg-surface-2">
                  Continue with single sign-on
                </a>
              </>
            )}
            <p className="text-center text-xs text-ink-2">
              New to the platform? <a href="/register" className="font-medium text-brand-ink hover:underline">Register your organisation</a>
            </p>
            <details className="text-xs text-ink-2">
              <summary className="cursor-pointer select-none">Demo users (Axion Mobility)</summary>
              <div className="mt-2 grid grid-cols-2 gap-1">
                {DEMO.map(([local, role]) => (
                  <button type="button" key={local} onClick={() => setEmail(`${local}@axion.example`)}
                    className="rounded-lg border border-line px-2 py-1 text-left transition hover:border-brand hover:bg-brand-soft">{role}</button>
                ))}
              </div>
            </details>
          </form>
        )}

        {step === 'choose' && (
          <div className="space-y-4 rounded-2xl border border-line bg-surface p-7 shadow-raised">
            <div>
              <h2 className="text-base font-semibold text-ink">Choose an organisation</h2>
              <p className="mt-1 text-sm text-ink-2">{email} has an account in more than one organisation. You can switch later from the header.</p>
            </div>
            <ul className="space-y-2">
              {organisations.map((o) => {
                const Icon = o.kind === 'SUPPLIER' || o.supplierUser ? Factory : Building2;
                return (
                  <li key={o.code}>
                    <button type="button" disabled={busy} onClick={() => choose(o.code)}
                      className="flex w-full items-center gap-3 rounded-lg border border-line px-3 py-2.5 text-left hover:border-brand hover:bg-surface-2 disabled:opacity-60">
                      <Icon size={20} className="shrink-0 text-brand-ink" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-ink">{o.name}</span>
                        <span className="block truncate text-xs text-ink-3">
                          {o.code} · {o.kind === 'SUPPLIER' ? 'Supplier' : 'Buyer'} organisation · {roleText(o.roles)}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <ProblemBox error={error} />
            <button type="button" onClick={restart} className="w-full text-center text-xs text-ink-3 hover:text-ink">Use a different account</button>
          </div>
        )}

        {step === 'mfa' && (
          <form onSubmit={submitCode} className="space-y-4 rounded-2xl border border-line bg-surface p-7 shadow-raised">
            <div>
              <h2 className="text-base font-semibold text-ink">Two-step verification</h2>
              <p className="mt-1 text-sm text-ink-2">Enter the 6-digit code from your authenticator app.</p>
            </div>
            <div className="space-y-1">
              <label htmlFor="code" className="text-xs font-medium text-ink-2">Authentication code</label>
              <Input id="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength={8} autoFocus required
                value={code} onChange={(e) => setCode(e.target.value)} className="font-mono tracking-[0.3em]" />
            </div>
            <ProblemBox error={error} />
            <Button type="submit" variant="primary" busy={busy} className="w-full py-2">Verify</Button>
            <button type="button" onClick={restart} className="w-full text-center text-xs text-ink-3 hover:text-ink">Use a different account</button>
          </form>
        )}

        {step === 'enrol' && (
          <div className="space-y-4 rounded-2xl border border-line bg-surface p-7 shadow-raised">
            <div>
              <h2 className="text-base font-semibold text-ink">Set up two-step verification</h2>
              <p className="mt-1 text-sm text-ink-2">
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
            <button type="button" onClick={restart} className="w-full text-center text-xs text-ink-3 hover:text-ink">Back to sign-in</button>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
