'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useState } from 'react';
import { Button, Field, Input, Loading, ProblemBox } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';

// Account activation and password reset from an administrator's single-use link. Public: no session; the API validates the token.

type LinkInfo = { purpose: 'ACTIVATION' | 'PASSWORD_RESET'; email: string; name: string; tenant: string; tenantCode: string; expiresAt: string };

export default function ActivatePage() {
  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[#F4F6FB] text-slate-900">
      <div className="mx-auto max-w-md px-4 py-10">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#1A56DB] font-bold text-white">α</span>
          <div>
            <p className="text-sm font-semibold">Purchasing Intelligence Cloud</p>
            <p className="text-xs text-slate-500">Set your password</p>
          </div>
        </div>
        <Suspense fallback={<Loading />}>
          <Activation />
        </Suspense>
      </div>
    </div>
  );
}

function passwordProblems(password: string, email: string, name: string): string[] {
  const out: string[] = [];
  if (password.length < 12) out.push('at least 12 characters');
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (classes < 3) out.push('mix three of: lower-case, upper-case, digits, symbols');
  const lowered = password.toLowerCase();
  const local = email.split('@')[0]?.toLowerCase() ?? '';
  if (local.length >= 4 && lowered.includes(local)) out.push('must not contain your e-mail name');
  if (name.toLowerCase().split(/[^a-z0-9]+/).some((w) => w.length >= 4 && lowered.includes(w))) out.push('must not contain your name');
  return out;
}

function Notice({ title, text }: { title: string; text: string }) {
  return (
    <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-5">
      <p className="font-semibold text-amber-900">{title}</p>
      <p className="mt-1 text-sm text-amber-900">{text}</p>
      <Link href="/pic/login" className="mt-3 inline-block text-sm font-medium text-[#1A56DB] hover:underline">Go to sign-in →</Link>
    </div>
  );
}

function Activation() {
  const token = useSearchParams().get('token') ?? '';
  const info = useApi<LinkInfo>(token ? `/public/user-tokens/${encodeURIComponent(token)}` : null);
  if (!token) return <Notice title="Link incomplete" text="Open the link from your e-mail. It contains a one-time token." />;
  if (info.isLoading) return <Loading text="Checking your link…" />;
  if (info.error || !info.data) {
    const code = info.error?.problem?.code;
    const text = code === 'LINK_USED' ? 'This link has already been used. Sign in, or ask an administrator for a new link.'
      : code === 'LINK_EXPIRED' ? 'This link has expired. Ask an administrator for a new link.'
        : code === 'LINK_REVOKED' ? 'This link was replaced by a newer one. Use the latest e-mail, or ask an administrator.'
          : info.error?.message ?? 'This link is not valid.';
    return <Notice title="This link cannot be used" text={text} />;
  }
  return <PasswordForm token={token} info={info.data} />;
}

function PasswordForm({ token, info }: { token: string; info: LinkInfo }) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const activation = info.purpose === 'ACTIVATION';

  async function submit(e: FormEvent) {
    e.preventDefault();
    const found: string[] = [];
    const weak = passwordProblems(password, info.email, info.name);
    if (weak.length) found.push(`Password: ${weak.join('; ')}.`);
    if (password !== confirm) found.push('The two passwords do not match.');
    setErrors(found);
    setFailure(null);
    if (found.length) return;
    setBusy(true);
    try {
      await api.post(`/public/user-tokens/${encodeURIComponent(token)}/complete`, { password }, { idempotencyKey: false });
      setDone(true);
      setPassword('');
      setConfirm('');
    } catch (err) {
      setFailure(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div role="status" className="rounded-xl border border-emerald-300 bg-emerald-50 p-5">
        <p className="font-semibold text-emerald-900">{activation ? 'Your account is active' : 'Your password was changed'}</p>
        <p className="mt-1 text-sm text-emerald-900">Sign in as {info.email} with the organisation code <span className="font-mono">{info.tenantCode}</span>.
          Approver, finance and administrator roles are asked to register an authenticator app at the first sign-in.</p>
        <Link href="/pic/login" className="mt-3 inline-block text-sm font-medium text-[#1A56DB] hover:underline">Go to sign-in →</Link>
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5" noValidate>
      <div>
        <h1 className="text-lg font-semibold">{activation ? `Welcome, ${info.name}` : `Reset the password for ${info.name}`}</h1>
        <p className="text-sm text-slate-600">{info.tenant} · {info.email}. The link works once and expires on {date(info.expiresAt)}.</p>
      </div>
      <Field label="New password" hint="At least 12 characters, mixing three of: lower-case, upper-case, digits, symbols">
        {(id) => <Input id={id} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </Field>
      <Field label="Repeat the password">
        {(id) => <Input id={id} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
      </Field>
      {errors.length > 0 && (
        <ul role="alert" className="list-disc rounded-lg border border-red-200 bg-red-50 py-2 pl-7 pr-3 text-sm text-red-900">
          {errors.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}
      <ProblemBox error={failure} />
      <Button type="submit" variant="primary" busy={busy}>{activation ? 'Activate account' : 'Change password'}</Button>
    </form>
  );
}
