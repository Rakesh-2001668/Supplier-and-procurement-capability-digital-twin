'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { Briefcase, Factory, MailCheck } from 'lucide-react';
import { Button, Field, Input, Loading, ProblemBox, Select } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { useApi } from '@/lib/pic/hooks';
import { STATES } from '../pic/register/tax';

// Organisation registration (public): the company chooses buyer or supplier, registers with its shared company mailbox and names its first
// administrator. A confirmation link goes to the shared mailbox; the AlphaHelion platform team then reviews the request.

type Status = { enabled: boolean; openKinds: string[]; sharedMailboxes: string[]; templates: string[] };
type Kind = 'BUYER' | 'SUPPLIER';

const TEMPLATE_LABELS: Record<string, string> = {
  MANUFACTURING: 'Manufacturing', CONSTRUCTION: 'Construction', IT_SERVICES: 'IT services', LOGISTICS: 'Logistics', HEALTHCARE: 'Healthcare',
  GENERAL: 'General',
};

export default function RegisterPage() {
  const status = useApi<Status>('/public/registrations/status');
  const [kind, setKind] = useState<Kind | null>(null);
  return (
    <div className="min-h-screen bg-[#F4F6FB] text-slate-900">
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div className="mb-6 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#1A56DB] font-bold text-white">α</span>
            <div>
              <p className="text-sm font-semibold">AlphaHelion Purchasing Intelligence Cloud</p>
              <p className="text-xs text-slate-500">Register your organisation</p>
            </div>
          </div>
          <Link href="/signin" className="text-sm font-medium text-[#1A56DB] hover:underline">Already registered? Sign in</Link>
        </div>
        {status.isLoading ? <Loading /> : (
          <>
            {status.data && !status.data.enabled && (
              <div role="status" className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
                Registration opens shortly. Until then, contact the AlphaHelion team to have your organisation set up.
              </div>
            )}
            <section className="rounded-xl border border-slate-200 bg-white p-6">
              <h1 className="text-lg font-semibold">1. Your organisation is a</h1>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <KindCard selected={kind === 'BUYER'} onSelect={() => setKind('BUYER')} icon={<Briefcase size={28} aria-hidden />} title="Buyer"
                  text="We buy goods and services: plan demand, source, contract, order, receive and pay our suppliers." />
                <KindCard selected={kind === 'SUPPLIER'} onSelect={() => setKind('SUPPLIER')} icon={<Factory size={28} aria-hidden />} title="Supplier"
                  text="We supply buyers: answer RFQs, confirm orders, ship, invoice and show our capabilities." />
              </div>
              {kind === 'SUPPLIER' && !status.data?.openKinds.includes('SUPPLIER') && (
                <p role="status" className="mt-4 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                  Supplier organisations can register from the next release. Meanwhile your buyer can invite you to its supplier portal.
                </p>
              )}
            </section>
            {kind && status.data?.openKinds.includes(kind) && (
              <RegistrationForm kind={kind} status={status.data} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function KindCard({ selected, onSelect, icon, title, text }: { selected: boolean; onSelect: () => void; icon: React.ReactNode; title: string; text: string }) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected}
      className={`rounded-xl border-2 p-4 text-left transition ${selected ? 'border-[#1A56DB] bg-blue-50' : 'border-slate-200 hover:border-slate-300'}`}>
      <span className={selected ? 'text-[#1A56DB]' : 'text-slate-400'}>{icon}</span>
      <span className="mt-2 block text-base font-semibold">{title}</span>
      <span className="mt-1 block text-sm text-slate-600">{text}</span>
    </button>
  );
}

function RegistrationForm({ kind, status }: { kind: Kind; status: Status }) {
  const [form, setForm] = useState({
    companyName: '', country: 'IN', stateCode: '33', gstin: '', industryTemplate: 'MANUFACTURING', organisationEmail: '', adminName: '',
    adminEmail: '', adminPhone: '', authorisedByName: '', authorisedByDesignation: '', expectedUsers: '', acceptTerms: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.type === 'checkbox' ? (e.target as HTMLInputElement).checked : e.target.value }));
  const mailboxes = status.sharedMailboxes.map((m) => `${m}@`).join(', ');

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ detail: string }>('/public/registrations', {
        ...form, kind, gstin: form.gstin.trim().toUpperCase() || null, adminPhone: form.adminPhone.trim() || null,
        authorisedByName: form.authorisedByName.trim() || null, authorisedByDesignation: form.authorisedByDesignation.trim() || null,
        expectedUsers: form.expectedUsers ? Number(form.expectedUsers) : null, stateCode: form.country === 'IN' ? form.stateCode : null,
      }, { idempotencyKey: false });
      setDone(result.detail);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <section role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-6">
        <MailCheck size={28} className="text-emerald-700" aria-hidden />
        <h2 className="mt-2 text-lg font-semibold text-emerald-900">Check your shared mailbox</h2>
        <p className="mt-1 text-sm text-emerald-900">{done}</p>
      </section>
    );
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-6 rounded-xl border border-slate-200 bg-white p-6">
      <div>
        <h2 className="text-lg font-semibold">2. Organisation</h2>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <Field label="Registered company name" required>{(id) => <Input id={id} value={form.companyName} onChange={set('companyName')} required />}</Field>
          <Field label="Industry">{(id) => (
            <Select id={id} value={form.industryTemplate} onChange={set('industryTemplate')}
              options={status.templates.map((t) => ({ value: t, label: TEMPLATE_LABELS[t] ?? t }))} />
          )}</Field>
          <Field label="Country">{(id) => (
            <Select id={id} value={form.country} onChange={set('country')} options={[{ value: 'IN', label: 'India' }, { value: 'AE', label: 'United Arab Emirates' },
              { value: 'SG', label: 'Singapore' }, { value: 'GB', label: 'United Kingdom' }, { value: 'US', label: 'United States' }, { value: 'DE', label: 'Germany' }]} />
          )}</Field>
          {form.country === 'IN' && (
            <Field label="State of the registered office" required>{(id) => (
              <Select id={id} value={form.stateCode} onChange={set('stateCode')} options={STATES.map((s) => ({ value: s.code, label: `${s.code} ${s.name}` }))} />
            )}</Field>
          )}
          {form.country === 'IN' && (
            <Field label="GSTIN" hint="Optional now; the platform team may ask for it">{(id, d) => (
              <Input id={id} aria-describedby={d} value={form.gstin} onChange={set('gstin')} maxLength={15} className="font-mono uppercase" />
            )}</Field>
          )}
          <Field label="Company shared mailbox" required hint={`On your company's own domain: ${mailboxes}`}>{(id, d) => (
            <Input id={id} aria-describedby={d} type="email" value={form.organisationEmail} onChange={set('organisationEmail')} placeholder="purchase@yourcompany.com" required />
          )}</Field>
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold">3. First administrator</h2>
        <p className="mt-1 text-sm text-slate-600">The person who will set up your organisation on the platform (users, roles, rules). They sign in with their own e-mail,
          password and two-step verification.</p>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <Field label="Full name" required>{(id) => <Input id={id} value={form.adminName} onChange={set('adminName')} required />}</Field>
          <Field label="Personal work e-mail" required hint="On the same company domain as the shared mailbox">{(id, d) => (
            <Input id={id} aria-describedby={d} type="email" value={form.adminEmail} onChange={set('adminEmail')} placeholder="firstname.lastname@yourcompany.com" required />
          )}</Field>
          <Field label="Phone">{(id) => <Input id={id} value={form.adminPhone} onChange={set('adminPhone')} placeholder="+91 98400 12345" />}</Field>
          <Field label="Expected number of users">{(id) => <Input id={id} type="number" min={1} value={form.expectedUsers} onChange={set('expectedUsers')} />}</Field>
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold">4. Authorised by <span className="text-sm font-normal text-slate-500">(optional)</span></h2>
        <p className="mt-1 text-sm text-slate-600">A senior person who authorises this registration, for example a director. Shown to the platform team; this person does not get an account.</p>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <Field label="Name">{(id) => <Input id={id} value={form.authorisedByName} onChange={set('authorisedByName')} />}</Field>
          <Field label="Designation">{(id) => <Input id={id} value={form.authorisedByDesignation} onChange={set('authorisedByDesignation')} placeholder="Managing Director" />}</Field>
        </div>
      </div>

      <label className="flex items-start gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={form.acceptTerms} onChange={set('acceptTerms')} className="mt-1" required />
        <span>I accept the terms of use and the privacy notice of AlphaHelion Purchasing Intelligence Cloud on behalf of the organisation.</span>
      </label>
      <ProblemBox error={error} />
      <Button type="submit" variant="primary" busy={busy} disabled={!status.enabled} className="w-full py-2">
        Register {kind === 'BUYER' ? 'buyer' : 'supplier'} organisation
      </Button>
    </form>
  );
}
