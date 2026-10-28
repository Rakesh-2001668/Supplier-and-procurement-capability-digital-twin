'use client';

import { FormEvent, useState } from 'react';
import { Button, Input } from '@/components/pic/ui';

export type Enrolment = { factorId: string; secret: string; otpauthUri: string; issuer: string; digits: number; period: number; algorithm: string };

/** Manual-entry authenticator setup (no QR library is installed): the key, the otpauth link and the confirmation code. */
export function AuthenticatorSetup({ enrolment, busy, onConfirm }: { enrolment: Enrolment; busy?: boolean; onConfirm: (code: string) => void }) {
  const [code, setCode] = useState('');
  const [copied, setCopied] = useState<string | null>(null);
  const grouped = enrolment.secret.match(/.{1,4}/g)?.join(' ') ?? enrolment.secret;

  async function copy(what: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(what);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      setCopied(null);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    onConfirm(code.replace(/\s/g, ''));
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-700">
        <li>In your authenticator app choose <span className="font-medium">Add account → Enter a setup key</span>.</li>
        <li>Account: your work e-mail. Key type: time-based ({enrolment.algorithm}, {enrolment.digits} digits, {enrolment.period} s).</li>
        <li>Enter the key below, then type the code the app shows.</li>
      </ol>
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <p className="text-xs font-medium text-slate-500">Setup key ({enrolment.issuer})</p>
        <p className="mt-1 break-all font-mono text-base tracking-wider text-slate-900" aria-label="Setup key">{grouped}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button type="button" onClick={() => copy('key', enrolment.secret)}>{copied === 'key' ? 'Copied' : 'Copy key'}</Button>
          <Button type="button" onClick={() => copy('uri', enrolment.otpauthUri)}>{copied === 'uri' ? 'Copied' : 'Copy otpauth link'}</Button>
          <a href={enrolment.otpauthUri} className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50">
            Open in authenticator app
          </a>
        </div>
        <p className="mt-2 break-all font-mono text-[11px] text-slate-500">{enrolment.otpauthUri}</p>
        <p className="mt-2 text-xs text-slate-500">The key is shown only now. Do not share it; anyone with it can generate your codes.</p>
      </div>
      <div className="space-y-1">
        <label htmlFor="totp-confirm" className="text-xs font-medium text-slate-700">Code from the app</label>
        <Input id="totp-confirm" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength={8} required
          value={code} onChange={(e) => setCode(e.target.value)} className="font-mono tracking-[0.3em]" />
      </div>
      <Button type="submit" variant="primary" busy={busy} className="w-full py-2">Confirm and activate</Button>
    </form>
  );
}
