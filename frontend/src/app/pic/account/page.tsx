'use client';

import { FormEvent, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Facts, Input, Loading, PageHeader, ProblemBox, StatusChip } from '@/components/pic/ui';
import { useToast } from '@/components/pic/toast';
import { api, ApiError } from '@/lib/pic/api';
import { dateTime, label } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { AuthenticatorSetup, Enrolment } from './_authenticator';

type Me = { userId: string; user: string; name: string; tenant: string; roles: string[]; attributes: Record<string, unknown>; supplierId: string | null };
type MfaStatus = { enrolled: boolean; pending: boolean; confirmedAt: string | null; enforced: boolean; required: boolean; issuer: string };

async function disableTotp(code: string) {
  const response = await fetch('/api/pic/v1/me/mfa/totp', {
    method: 'DELETE', headers: { 'content-type': 'application/json', accept: 'application/json' }, body: JSON.stringify({ code }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError({ status: response.status, code: data?.code ?? 'ERROR', ...data });
  return data;
}

function SecurityCard() {
  const client = useQueryClient();
  const toast = useToast();
  const status = useApi<MfaStatus>('/me/mfa');
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [disableCode, setDisableCode] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await client.invalidateQueries({ queryKey: ['/me/mfa'] });
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const start = () => run(async () => setEnrolment(await api.post<Enrolment>('/me/mfa/totp')));
  const confirm = (code: string) => run(async () => {
    await api.post('/me/mfa/totp/confirm', { code });
    setEnrolment(null);
    toast.success('Authenticator activated. You will be asked for a code at every sign-in.');
  });
  const disable = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await disableTotp(disableCode.replace(/\s/g, ''));
      setDisableCode('');
      toast.success('Authenticator removed');
    });
  };

  if (status.isLoading) return <Card title="Two-step verification (TOTP)"><Loading /></Card>;
  if (status.error) return <Card title="Two-step verification (TOTP)"><ProblemBox error={status.error} /></Card>;
  const s = status.data!;
  return (
    <Card title="Two-step verification (TOTP)" actions={<StatusChip status={s.enrolled ? 'ACTIVE' : s.pending || enrolment ? 'PENDING' : 'NOT_SET_UP'} />}>
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          A time-based one-time code from an authenticator app is asked at every password sign-in.
          {s.required ? ' Your role requires it (MFA policy is enforced for approvers, finance and administrators).'
            : s.enforced ? ' It is optional for your role.' : ' Your organisation has not made it mandatory yet; approvers, finance and administrators should enable it.'}
          {' '}Single sign-on uses the multi-factor authentication of your identity provider instead.
        </p>
        {s.enrolled ? (
          <>
            <Facts items={[['Status', 'Active'], ['Activated', dateTime(s.confirmedAt)], ['Issuer', s.issuer], ['Mandatory for you', s.required ? 'Yes' : 'No']]} />
            {s.required ? (
              <p className="text-xs text-slate-500">Because MFA is mandatory for your role, the authenticator cannot be removed. Ask your administrator to reset it if you lose the device.</p>
            ) : (
              <form onSubmit={disable} className="flex flex-wrap items-end gap-2">
                <div className="space-y-1">
                  <label htmlFor="disable-code" className="text-xs font-medium text-slate-700">Current code (to remove the authenticator)</label>
                  <Input id="disable-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength={8} required
                    value={disableCode} onChange={(e) => setDisableCode(e.target.value)} className="w-40 font-mono tracking-[0.2em]" />
                </div>
                <Button type="submit" variant="danger" busy={busy}>Remove authenticator</Button>
              </form>
            )}
          </>
        ) : enrolment ? (
          <div className="max-w-lg"><AuthenticatorSetup enrolment={enrolment} busy={busy} onConfirm={confirm} /></div>
        ) : (
          <Button variant="primary" busy={busy} onClick={start}>{s.pending ? 'Restart setup' : 'Set up authenticator app'}</Button>
        )}
        <ProblemBox error={error} />
      </div>
    </Card>
  );
}

export default function AccountPage() {
  const me = useApi<Me>('/me');
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Account" title="My account & security" subtitle="Your identity, roles and sign-in protection." />
      <Card title="Profile">
        {me.isLoading ? <Loading /> : me.error ? <ProblemBox error={me.error} /> : me.data && (
          <Facts items={[
            ['Name', me.data.name], ['E-mail', me.data.user], ['Organisation', me.data.tenant],
            ['Roles', me.data.roles.map((r) => label(r)).join(', ') || '–'],
            ['Plants', Array.isArray(me.data.attributes?.plants) ? (me.data.attributes.plants as string[]).join(', ') : 'All'],
            ['Company codes', Array.isArray(me.data.attributes?.company_codes) ? (me.data.attributes.company_codes as string[]).join(', ') : 'All'],
          ]} />
        )}
      </Card>
      <SecurityCard />
    </div>
  );
}
