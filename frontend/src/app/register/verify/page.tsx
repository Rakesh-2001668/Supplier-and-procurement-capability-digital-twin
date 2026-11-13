'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { Loading } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';

// Confirmation of an organisation registration from the link sent to the company's shared mailbox (single use, 24 hours).

type Result = { status: string; number: string; company: string; detail: string };

export default function VerifyRegistrationPage() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <div className="mx-auto max-w-xl px-4 py-16">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-brand font-bold text-white">α</span>
          <p className="text-sm font-semibold">AlphaHelion Purchasing Intelligence Cloud</p>
        </div>
        <Suspense fallback={<Loading />}><Confirm /></Suspense>
      </div>
    </div>
  );
}

function Confirm() {
  const token = useSearchParams().get('token') ?? '';
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;  // the link works once: never post it twice (React strict mode runs effects twice in development)
    api.post<Result>('/public/registrations/verify', { token }, { idempotencyKey: false }).then(setResult).catch((err) => setError(err as ApiError));
  }, [token]);

  if (!token) return <Box tone="warn" title="Link incomplete" text="Open the link from the confirmation e-mail. It contains a one-time code." />;
  if (error) {
    const expired = error.problem?.code === 'LINK_EXPIRED';
    return <Box tone="warn" title={expired ? 'This link has expired' : 'This link cannot be used'}
      text={expired ? 'Register again; a new link will be sent to the shared mailbox.' : 'It was already used or is not valid. If you confirmed it before, the request is with the platform team.'}
      link={expired ? { href: '/register', label: 'Register again' } : undefined} />;
  }
  if (!result) return <Loading text="Confirming the registration…" />;
  return <Box tone="good" title={`${result.company}: request ${result.number} confirmed`} text={result.detail} link={{ href: '/signin', label: 'Go to sign-in' }} />;
}

function Box({ tone, title, text, link }: { tone: 'good' | 'warn'; title: string; text: string; link?: { href: string; label: string } }) {
  const styles = tone === 'good' ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-amber-300 bg-amber-50 text-amber-900';
  return (
    <div role="status" className={`rounded-xl border p-6 ${styles}`}>
      <p className="text-lg font-semibold">{title}</p>
      <p className="mt-1 text-sm">{text}</p>
      {link && <Link href={link.href} className="mt-3 inline-block text-sm font-medium text-brand-ink hover:underline">{link.label} →</Link>}
    </div>
  );
}
