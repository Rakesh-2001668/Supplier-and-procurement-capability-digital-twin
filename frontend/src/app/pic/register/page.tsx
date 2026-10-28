'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { FormEvent, Suspense, useState } from 'react';
import { Button, Field, Input, Loading, ProblemBox, Select } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { date } from '@/lib/pic/format';
import { useApi } from '@/lib/pic/hooks';
import { emailValid, gstinProblems, panValid, phoneValid, pinValid, STATES } from './tax';

// F8-01 supplier self-registration from an invitation link. Public: no session; the API validates the one-time token.

type Invitation = { legalName: string; email: string; categories: string[]; tenant: string; tenantCode: string; expiresAt: string };
type Registered = { supplier: string; legalName: string; status: string; screening: string; qualifications: string[];
  login: { tenant: string; email: string; mfaEnrolled: boolean }; next: string };

export default function RegisterPage() {
  return (
    // Covers the workspace shell: invitees have no session and see only the registration form.
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[#F4F6FB] text-slate-900">
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#1A56DB] font-bold text-white">α</span>
          <div>
            <p className="text-sm font-semibold">Purchasing Intelligence Cloud</p>
            <p className="text-xs text-slate-500">Supplier registration</p>
          </div>
        </div>
        <Suspense fallback={<Loading />}>
          <Registration />
        </Suspense>
      </div>
    </div>
  );
}

function passwordProblems(password: string, email: string, legalName: string): string[] {
  const out: string[] = [];
  if (password.length < 12) out.push('at least 12 characters');
  const classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (classes < 3) out.push('mix three of: lower-case, upper-case, digits, symbols');
  const lowered = password.toLowerCase();
  const local = email.split('@')[0]?.toLowerCase() ?? '';
  if (local.length >= 4 && lowered.includes(local)) out.push('must not contain your e-mail name');
  const words = legalName.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length >= 4 && !['private', 'limited', 'india'].includes(w));
  if (words.some((w) => lowered.includes(w))) out.push('must not contain your company name');
  return out;
}

function Registration() {
  const token = useSearchParams().get('token') ?? '';
  const invitation = useApi<Invitation>(token ? `/public/invitations/${encodeURIComponent(token)}` : null);
  if (!token) {
    return <Notice title="Registration link incomplete" text="Open the link from your invitation e-mail. It contains a one-time token." />;
  }
  if (invitation.isLoading) return <Loading text="Checking your invitation…" />;
  if (invitation.error || !invitation.data) {
    const code = invitation.error?.problem?.code;
    const text = code === 'INVITATION_USED' ? 'This link has already been used to register. Sign in to the supplier portal instead.'
      : code === 'INVITATION_EXPIRED' ? 'This link has expired. Ask the buyer who invited you for a new invitation.'
        : code === 'INVITATION_REVOKED' ? 'This invitation was withdrawn. Contact the buyer who invited you.'
          : invitation.error?.message ?? 'This registration link is not valid.';
    return <Notice title="This link cannot be used" text={text} signIn={code === 'INVITATION_USED'} />;
  }
  return <RegistrationForm token={token} invitation={invitation.data} />;
}

function Notice({ title, text, signIn }: { title: string; text: string; signIn?: boolean }) {
  return (
    <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-5">
      <p className="font-semibold text-amber-900">{title}</p>
      <p className="mt-1 text-sm text-amber-900">{text}</p>
      {signIn && <Link href="/pic/login" className="mt-3 inline-block text-sm font-medium text-[#1A56DB] hover:underline">Go to sign-in →</Link>}
    </div>
  );
}

function RegistrationForm({ token, invitation }: { token: string; invitation: Invitation }) {
  const [legalName, setLegalName] = useState(invitation.legalName);
  const [gstin, setGstin] = useState('');
  const [pan, setPan] = useState('');
  const [line1, setLine1] = useState('');
  const [line2, setLine2] = useState('');
  const [city, setCity] = useState('');
  const [pin, setPin] = useState('');
  const [contactName, setContactName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [done, setDone] = useState<Registered | null>(null);

  const g = gstin.trim().toUpperCase();
  const stateCode = g.slice(0, 2);
  const stateName = STATES.find((s) => s.code === stateCode)?.name;
  const effectivePan = pan || (g.length >= 12 ? g.slice(2, 12) : '');

  const validate = () => {
    const out: string[] = [];
    if (legalName.trim().length < 3) out.push('Legal name is required.');
    out.push(...gstinProblems(g, effectivePan));
    if (!panValid(effectivePan)) out.push('PAN must be 5 letters, 4 digits and a letter.');
    if (!line1.trim() || !city.trim()) out.push('Registered address line 1 and city are required.');
    if (!pinValid(pin)) out.push('PIN code must be 6 digits.');
    if (contactName.trim().length < 2) out.push('Contact name is required.');
    if (phone.trim() && !phoneValid(phone)) out.push('Phone must be 9–18 digits, optionally starting with +.');
    const weak = passwordProblems(password, invitation.email, legalName);
    if (weak.length) out.push(`Password: ${weak.join('; ')}.`);
    if (password !== confirm) out.push('The two passwords do not match.');
    if (!emailValid(invitation.email)) out.push('The invited e-mail address is not valid; ask for a new invitation.');
    return out;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v = validate();
    setErrors(v);
    setFailure(null);
    if (v.length) return;
    setBusy(true);
    try {
      const result = await api.post<Registered>(`/public/invitations/${encodeURIComponent(token)}/register`, {
        legalName: legalName.trim(), gstin: g, pan: effectivePan.toUpperCase(), stateCode,
        address: { line1: line1.trim(), line2: line2.trim() || undefined, city: city.trim(), stateCode, pin: pin.trim(), country: 'IN' },
        contactName: contactName.trim(), email: invitation.email, phone: phone.trim() || undefined, password,
      }, { idempotencyKey: false });
      setDone(result);
      setPassword('');
      setConfirm('');
    } catch (err) {
      setFailure(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <section className="rounded-xl border border-emerald-200 bg-white p-6">
        <h1 className="text-xl font-semibold text-[#0B1020]">Registration received</h1>
        <p className="mt-2 text-sm text-slate-700">{done.legalName} is registered with {invitation.tenant} as supplier <span className="font-mono">{done.supplier}</span>.
          {done.qualifications.length ? ` Qualification has started for ${done.qualifications.join(', ')}.` : ''}</p>
        {done.status === 'BLOCKED' && <p className="mt-2 text-sm text-red-800">Screening needs a manual review before you can trade; the buyer will contact you.</p>}
        <p className="mt-2 text-sm text-slate-700">{done.next}</p>
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm">
          <p>Sign in with company code <span className="font-mono font-semibold">{done.login.tenant}</span> and <span className="font-medium">{done.login.email}</span>.</p>
          <p className="text-xs text-slate-500">You will be asked to set up two-factor authentication when your buyer requires it.</p>
        </div>
        <Link href="/pic/login" className="mt-4 inline-flex items-center rounded-lg bg-[#1A56DB] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1747b8]">Sign in to the supplier portal</Link>
      </section>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-[#0B1020]">Register as a supplier of {invitation.tenant}</h1>
        <p className="mt-1 text-sm text-slate-600">Invited for {invitation.categories.join(', ')} · link valid until {date(invitation.expiresAt)} · login {invitation.email}</p>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold">Company and tax registration</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2"><Field label="Legal name (as on the GST certificate) *">{(id) => <Input id={id} value={legalName} onChange={(e) => setLegalName(e.target.value)} autoComplete="organization" />}</Field></div>
          <Field label="GSTIN *" hint={stateName ? `State: ${stateCode} · ${stateName}` : '15 characters, e.g. 33AAACN4821Q1Z…'}>{(id) => (
            <Input id={id} value={gstin} maxLength={15} onChange={(e) => setGstin(e.target.value.toUpperCase().replace(/\s/g, ''))} className="font-mono" />
          )}</Field>
          <Field label="PAN *" hint="Taken from the GSTIN; change only if it differs">{(id) => (
            <Input id={id} value={effectivePan} maxLength={10} onChange={(e) => setPan(e.target.value.toUpperCase())} className="font-mono" />
          )}</Field>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold">Registered address</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2"><Field label="Address line 1 *">{(id) => <Input id={id} value={line1} onChange={(e) => setLine1(e.target.value)} autoComplete="address-line1" />}</Field></div>
          <div className="md:col-span-2"><Field label="Address line 2">{(id) => <Input id={id} value={line2} onChange={(e) => setLine2(e.target.value)} autoComplete="address-line2" />}</Field></div>
          <Field label="City *">{(id) => <Input id={id} value={city} onChange={(e) => setCity(e.target.value)} autoComplete="address-level2" />}</Field>
          <Field label="PIN code *">{(id) => <Input id={id} value={pin} inputMode="numeric" maxLength={6} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} autoComplete="postal-code" />}</Field>
          <Field label="State" hint="Follows the GSTIN state code">{(id) => (
            <Select id={id} value={stateCode} disabled onChange={() => undefined}
              options={[{ value: '', label: 'Enter the GSTIN first' }, ...STATES.map((s) => ({ value: s.code, label: `${s.code} · ${s.name}` }))]} />
          )}</Field>
          <Field label="Country">{(id) => <Input id={id} value="India" disabled />}</Field>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold">Your portal login</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Contact name *">{(id) => <Input id={id} value={contactName} onChange={(e) => setContactName(e.target.value)} autoComplete="name" />}</Field>
          <Field label="Phone">{(id) => <Input id={id} value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" placeholder="+91 …" />}</Field>
          <Field label="E-mail (login)" hint="The invitation is bound to this address">{(id) => <Input id={id} value={invitation.email} disabled />}</Field>
          <div />
          <Field label="Password *" hint="12+ characters, three of: lower, upper, digits, symbols">{(id) => (
            <Input id={id} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          )}</Field>
          <Field label="Confirm password *">{(id) => <Input id={id} type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />}</Field>
        </div>
      </section>

      {errors.length > 0 && (
        <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Please correct</p>
          <ul className="mt-1 list-disc pl-5">{errors.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      {failure && (
        <div className="space-y-1">
          <ProblemBox error={failure} />
          {Array.isArray(failure.problem?.errors) && (failure.problem.errors as string[]).length > 1 && (
            <ul className="list-disc pl-6 text-sm text-red-900">{(failure.problem.errors as string[]).map((x) => <li key={x}>{x}</li>)}</ul>
          )}
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500">Your GSTIN is stored encrypted and shown masked. The buyer screens new suppliers (duplicates, sanctions) before trading.</p>
        <Button type="submit" variant="primary" busy={busy}>Register</Button>
      </div>
    </form>
  );
}
