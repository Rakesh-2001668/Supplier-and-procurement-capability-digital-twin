'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Button, Card, Field, Input, PageHeader, ProblemBox, Select } from '@/components/pic/ui';
import { api, ApiError } from '@/lib/pic/api';
import { useCommand } from '@/lib/pic/hooks';

const GSTIN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SEGMENTS = [
  { value: '', label: 'Not set' },
  { value: 'STRATEGIC', label: 'Strategic' },
  { value: 'LEVERAGE', label: 'Leverage' },
  { value: 'BOTTLENECK', label: 'Bottleneck' },
  { value: 'ROUTINE', label: 'Routine' },
];

export default function RegisterSupplier() {
  const router = useRouter();
  const [code, setCode] = useState('');
  const [legalName, setLegalName] = useState('');
  const [gstin, setGstin] = useState('');
  const [pan, setPan] = useState('');
  const [stateCode, setStateCode] = useState('');
  const [email, setEmail] = useState('');
  const [categories, setCategories] = useState('');
  const [terms, setTerms] = useState('N60');
  const [incoterms, setIncoterms] = useState('');
  const [segment, setSegment] = useState('');
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const cats = categories.split(',').map((c) => c.trim().toUpperCase()).filter(Boolean);
  const errors: Record<string, string> = {};
  if (!legalName.trim()) errors.legal = 'Legal name is required.';
  if (gstin.length !== 15) errors.gstin = 'GSTIN has 15 characters.';
  else if (!GSTIN.test(gstin)) errors.gstin = 'GSTIN format looks wrong (e.g. 33AABCT1234F1Z5).';
  if (pan.length !== 10) errors.pan = 'PAN has 10 characters.';
  else if (!PAN.test(pan)) errors.pan = 'PAN format looks wrong (e.g. AABCT1234F).';
  else if (gstin.length === 15 && gstin.slice(2, 12) !== pan) errors.pan = 'PAN should match characters 3–12 of the GSTIN.';
  if (!/^[0-9]{2}$/.test(stateCode)) errors.state = 'State code is two digits (e.g. 33 for Tamil Nadu).';
  else if (gstin.length === 15 && gstin.slice(0, 2) !== stateCode) errors.state = 'State code should match the first two digits of the GSTIN.';
  if (!EMAIL.test(email)) errors.email = 'Enter a valid contact e-mail.';
  if (!cats.length) errors.cats = 'Give at least one category.';
  if (!terms.trim()) errors.terms = 'Payment terms are required.';
  const show = (k: string) => (attempted && errors[k] ? <p className="text-xs text-red-700">{errors[k]}</p> : null);

  const register = useCommand(() => api.post<{ code: string }>('/suppliers', {
    code: code.trim().toUpperCase() || undefined, legal_name: legalName.trim(), gstin, pan, state_code: stateCode, contact_email: email.trim(),
    categories: cats, payment_terms: terms.trim(), incoterms: incoterms.trim() || undefined, segment: segment || undefined,
  }), {
    success: (r) => `${r.code} registered – invite the supplier to complete the profile`,
    onSuccess: (r) => router.push(`/pic/suppliers/${encodeURIComponent(r.code)}`),
  });

  const submit = () => {
    setAttempted(true);
    setError(null);
    if (Object.keys(errors).length) return;
    register.mutate(undefined, { onError: setError });
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="F8-01 · Supplier onboarding" title="Register supplier"
        subtitle="Registration creates the supplier in Registered status for each category. Tax IDs are encrypted and screened for duplicates and sanctions; the supplier then submits bank details and certificates before qualification." />
      <Card title="Company">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Supplier code" hint="Optional – generated if left empty.">{(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} maxLength={20} />}</Field>
          <div className="md:col-span-2">
            <Field label="Legal name">{(id) => <Input id={id} value={legalName} onChange={(e) => setLegalName(e.target.value)} required aria-invalid={attempted && !!errors.legal} />}</Field>
            {show('legal')}
          </div>
          <div>
            <Field label="GSTIN (15 characters)">{(id) => <Input id={id} value={gstin} maxLength={15} required aria-invalid={attempted && !!errors.gstin}
              onChange={(e) => {
                const v = e.target.value.toUpperCase().replace(/\s/g, '');
                setGstin(v);
                if (v.length >= 2 && !stateCode) setStateCode(v.slice(0, 2));
                if (v.length >= 12 && !pan) setPan(v.slice(2, 12));
              }} className="font-mono" />}</Field>
            {show('gstin')}
          </div>
          <div>
            <Field label="PAN (10 characters)">{(id) => <Input id={id} value={pan} maxLength={10} required aria-invalid={attempted && !!errors.pan}
              onChange={(e) => setPan(e.target.value.toUpperCase().replace(/\s/g, ''))} className="font-mono" />}</Field>
            {show('pan')}
          </div>
          <div>
            <Field label="State code">{(id) => <Input id={id} value={stateCode} maxLength={2} inputMode="numeric" required aria-invalid={attempted && !!errors.state} onChange={(e) => setStateCode(e.target.value.replace(/\D/g, ''))} />}</Field>
            {show('state')}
          </div>
          <div>
            <Field label="Contact e-mail">{(id) => <Input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required aria-invalid={attempted && !!errors.email} />}</Field>
            {show('email')}
          </div>
          <div className="md:col-span-2">
            <Field label="Categories (comma-separated)" hint="e.g. ALU-DIECAST, TOOLING-SERVICES">{(id) => <Input id={id} value={categories} onChange={(e) => setCategories(e.target.value)} required aria-invalid={attempted && !!errors.cats} />}</Field>
            {show('cats')}
          </div>
        </div>
      </Card>
      <Card title="Commercial defaults">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <Field label="Payment terms" hint="e.g. N60 = 60 days net">{(id) => <Input id={id} value={terms} onChange={(e) => setTerms(e.target.value.toUpperCase())} required />}</Field>
            {show('terms')}
          </div>
          <Field label="Incoterms" hint="Optional, e.g. FCA Coimbatore">{(id) => <Input id={id} value={incoterms} onChange={(e) => setIncoterms(e.target.value)} />}</Field>
          <Field label="Segment">{(id) => <Select id={id} value={segment} onChange={(e) => setSegment(e.target.value)} options={SEGMENTS} />}</Field>
        </div>
      </Card>
      <ProblemBox error={error} />
      <div className="flex justify-end gap-2">
        <Button onClick={() => router.push('/pic/suppliers')}>Cancel</Button>
        <Button variant="primary" busy={register.isPending} onClick={submit}>Register supplier</Button>
      </div>
    </div>
  );
}
